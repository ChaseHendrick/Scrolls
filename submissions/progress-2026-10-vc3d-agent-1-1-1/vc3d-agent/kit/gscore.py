"""Per-winding credit of a traced surface for the tracing stage of AutoPipeline: `kit surfbench gscore`.

Stage 2 of docs/plans/2026-10-09-autopipeline-bars.md, whose metric it implements as fixed there. A candidate tifxyz
in the frame of PHerc0139 volume 20250728140407 is labeled vertex by vertex with surfbench's frozen labels (d = 4
voxels, masks on, no seating). Its credit for a winding w is

  G_w = (labeled area of w in the band z [4352, 4864) within 4 voxels of the surface's vertices labeled w, counting
         only the part of the surface reached from its seed) / (labeled area of w in the band)

The reached part grows from the seed through runs of vertices of one winding and through label changes that are
seam boundaries, never through a transverse switch, a hole, a vertex outside every reference or a torn edge. A trace
that follows the spiral past its winding's seam is therefore not penalized and a transverse switch is. With no seed
nothing is reached and G_w is 0; the best component is credited only when asked (controls, perfect surfaces), never
on a report winding. The surface is gated on its transverse switch line per cm2 and its self-crossings per cm2, each
net of the same reference's own; in version 2 each is the largest rate over windows of the band's height, so a
defect of fixed size is not diluted on a large surface (version 1, whole-surface rates, is kept runnable). Both
thresholds come from planted controls by a fixed midpoint rule (choose_gates) and are frozen in GRULE; a gate that
cannot be measured makes the score invalid. Net correct area (w's covered area minus the surface's area on other
windings in the band that was not reached through a seam) is reported beside G_w.

  score     G_w, the gates and the net area of one surface for its winding(s)
  controls  the planted controls on the tune windings: the band surface itself, moved half a winding step, a seam
            join and a transverse join, confetti, a fold, no-grid stand-ins and (version 2) the fold and the
            transverse join planted in a whole mesh; each with a sham on which it must fail, and the gate thresholds
            they give

Every label comes from published traces and model output; nothing here is a reading. Needs numpy and scipy, and
VC3D's vc_tifxyz_selfcross for the self-crossing gate.
"""

import json
import math
import tempfile
import time
from pathlib import Path

from . import surfbench as sb

TUNE = list(sb.TUNE)
PLAN_REPORT = ["w043", "w044"] + [f"w{n:03d}" for n in range(47, 60)]
BAND_Z = [4352.0, 4864.0]

# Version 1, kept verbatim: frozen in 913f7a7 before any trace was scored with it (a note of the source repository, "Per-winding
# credit"). The gate thresholds come from the planted controls alone (choose_gates on `kit surfbench gscore
# --controls` over the 18 tune windings, 9 October 2026: switch positives up to 0.0313 and negatives from 0.1386,
# self-crossing positives up to 27.92 and negatives from 56.995), and every controls run recomputes them and is valid
# only if they still match. `--rule-version 1` still runs it; its gates are rates over the whole surface, which a
# fixed-size defect dilutes on a large trace (review of 10 October 2026), so version 2 replaces them.
GRULE_V1 = {
    "version": 1,
    "plan": "docs/plans/2026-10-09-autopipeline-bars.md, section 2 (tracing)",
    "surfbench_rule_digest": sb.RULE_DIGEST,     # labels: surfbench's frozen rule at d = 4, masks on, no seating
    "band_z": BAND_Z,                            # each report winding is one full turn here
    "credit_vox": 4.0,                           # w's labeled vertex within this of a reached vertex labeled w
    "reach": {
        "bridge_vertices": 5,        # a run may cross at most 5 vertices off every winding or over a gap
        "tear_factor": 3.0,          # an edge longer than 3 median edges is a tear, not an edge
        "seed_radius_vertices": 5,   # a seed vertex on no winding takes the nearest labeled vertex this close
        # with no seed (controls and perfect surfaces only): of the components holding at least best_min_share of the
        # largest one's area on the winding in the band (at most best_components, by area), the one credited most
        "best_components": 8,
        "best_min_share": 0.25,
        "link": "two regions of different windings are linked when boundary crossings between them outnumber "
                "switch crossings (surfbench's switch test, with no-reference runs of any length bridged)",
    },
    "gates": {
        # the surface's rate minus the reference's own rate must not exceed the threshold; choose_gates sets it at
        # the midpoint of the highest positive and the lowest negative control, floored to `step`, and it must clear
        # both by `margin`
        "switch": {"metric": "switch_line_cm_per_cm2", "threshold": 0.08, "step": 0.01, "margin": 0.02,
                   "reference": "whole mesh: the scored reference's whole mesh labelled as a candidate is"},
        "selfcross": {"metric": "transverse_per_cm2", "threshold": 42.0, "step": 1.0, "margin": 5.0,
                      "explain_vox": 4.0,
                      "reference": "local: the surface's contacts within explain_vox of a contact of the scored "
                                   "references' own meshes are theirs, at most as many as those reference contacts; "
                                   "per cm2 of the surface (a whole-mesh rate failed the first controls run, log)"},
    },
    "controls": {
        "half_step_pitch": 0.5,       # the band surface moved half its winding's local pitch along its normal...
        "half_step_max_kept": 0.2,    # ... keeps at most 20 % of its credit (loses at least 80 %)
        "sham_move_vox": 1.0,         # the half-step criterion applied to a 1 voxel move must fail
        "tolerance_vox": 2.0,         # measured, not a gate
        "seam_tolerance": 0.01,       # a seam join keeps both windings' credit within this
        "transverse_max_kept": 0.1,   # a transverse join keeps at most 10 % of the moved part's credit
        "confetti_tiles": 8,
        "confetti_tolerance": 0.005,  # confetti is credited its largest tile within this
        "nogrid_max": 0.05,
        "nogrid_windings": ["w030", "w031", "w036"],   # np.random.default_rng(1).choice(TUNE, 3, replace=False)
        # the plan's no-grid check in the report run (a real no-grid trace seeded on each): named now, not run here
        "nogrid_report_windings": ["w044", "w048", "w055"],   # np.random.default_rng(2).choice(PLAN_REPORT, 3, ...)
        "nogrid_planes": 2,           # random-orientation planes per winding beside the moved no-grid trace
        "nogrid_size": [122, 122],    # vertices, at the reference grid step (s1-nogrid's grid)
        "fold_back_cols": 4,
        "fold_offset_vox": 1.5,
        "seed": 0,
    },
    "aa": {
        # measured in the bar's Modal job, not here: the bar tracer run twice on each winding
        "windings": ["w027", "w028", "w031", "w032", "w034"],   # np.random.default_rng(0).choice(TUNE, 5, ...)
        "runs": 2,
        "statistic": "SD over the windings of the paired difference G_w(run 1) - G_w(run 2)",
        "floor": "max(0.10, 2 SD)",
    },
    "split": {"tune": TUNE, "report": PLAN_REPORT, "excluded": ["w045", "w046"],
              "note": "choices on w023 to w040; the report windings are scored once, under a committed run rule"},
}

# Version 2 (review of version 1, 10 October 2026, before any report winding was scored). Both gates are local: the
# largest rate over square windows of the band's height at every position on the surface's grid, so a defect of fixed
# size gives the same rate on a band-sized surface as on a whole mesh, and the self-crossing gate excuses the scored
# references' own contacts one to one. Whole-mesh controls (the fold and the transverse join planted in the band rows
# of a whole published mesh) must be caught. A trace with no seed gets G_w 0; a report winding takes its seed only
# from the trace's meta.json. A gate that cannot be measured makes the score invalid. The thresholds come from the
# planted controls by the same rule as version 1 (choose_gates), frozen on 14 October 2026 from the version 2 controls
# run on the 18 tune windings (a note of the source repository; Amendment 4 of
# a note of the source repository): switch positives up to 1.1213 (the w038 seam join) and
# negatives from 1.8852 (the w036 transverse join), self-crossing positives up to 290.723 (the w035 seam join) and
# negatives from 927.6371 (the w029 fold). Before the freeze both were None (digest 6da62ec433b2...).
GRULE = {
    "version": 2,
    "plan": "docs/plans/2026-10-09-autopipeline-bars.md, section 2 (tracing)",
    "surfbench_rule_digest": sb.RULE_DIGEST,     # labels: surfbench's frozen rule at d = 4, masks on, no seating
    "band_z": BAND_Z,                            # each report winding is one full turn here
    "credit_vox": 4.0,                           # w's labeled vertex within this of a reached vertex labeled w
    "reach": {
        "bridge_vertices": 5,        # a run may cross at most 5 vertices off every winding or over a gap
        "tear_factor": 3.0,          # an edge longer than 3 median edges is a tear, not an edge
        "seed_radius_vertices": 5,   # a seed vertex on no winding takes the nearest labeled vertex this close
        "seed": "the point given, else the seed in the trace's meta.json; with neither (and no best), nothing is "
                "reached and G_w is 0",
        "report_seed": "a report winding takes its seed only from the trace's meta.json: a given point and best are "
                       "refused",
        # best (controls and perfect surfaces only, never a report winding): of the components holding at least
        # best_min_share of the largest one's area on the winding in the band (at most best_components, by area), the
        # one credited most
        "best_components": 8,
        "best_min_share": 0.25,
        "link": "two regions of different windings are linked when boundary crossings between them outnumber "
                "switch crossings (surfbench's switch test, with no-reference runs of any length bridged)",
    },
    "window": {
        "side_vox": 512.0,           # the band's height: every planted defect is a line across the band rows
        "min_area_share": 0.5,       # a window counts when its area is at least half the largest window's
        "grid": "square windows of ceil(side_vox / the surface's median edge) grid vertices a side (the grid's own "
                "size where it is smaller), at every position",
    },
    "gates": {
        # the largest window rate minus the reference's own must not exceed the threshold; choose_gates sets it at the
        # midpoint of the highest positive and the lowest negative control, floored to `step`, and it must clear both
        # by `margin`
        "switch": {"metric": "switch_window_max", "threshold": 1.5, "step": 0.01, "margin": 0.02,
                   "rate": "switch line (surfbench's switch crossings at d = 4, one median edge each, half at each end "
                           "vertex) per scored cm2 in the window",
                   "reference": "whole mesh: the scored reference's whole mesh labelled as a candidate is, switch line "
                                "per scored cm2"},
        "selfcross": {"metric": "selfcross_window_max", "threshold": 609.0, "step": 1.0, "margin": 5.0,
                      "explain_vox": 4.0,
                      "rate": "VC3D's transverse contacts that are not the references', each at its nearest vertex, "
                              "per cm2 of the surface in the window",
                      "reference": "local: a contact within explain_vox of a contact site of a scored reference's "
                                   "whole mesh is that reference's, one to one (a maximum matching)"},
    },
    "unmeasured": "a gate whose rate or reference rate is missing (a tool failure, contacts without sites) makes the "
                  "score invalid",
    "controls": {
        "half_step_pitch": 0.5,       # the band surface moved half its winding's local pitch along its normal...
        "half_step_max_kept": 0.2,    # ... keeps at most 20 % of its credit (loses at least 80 %)
        "sham_move_vox": 1.0,         # the half-step criterion applied to a 1 voxel move must fail
        "tolerance_vox": 2.0,         # measured, not a gate
        "seam_tolerance": 0.01,       # a seam join keeps both windings' credit within this
        "transverse_max_kept": 0.1,   # a transverse join keeps at most 10 % of the moved part's credit
        "confetti_tiles": 8,
        "confetti_tolerance": 0.005,  # confetti is credited its largest tile within this
        "nogrid_max": 0.05,
        "nogrid_windings": ["w030", "w031", "w036"],   # np.random.default_rng(1).choice(TUNE, 3, replace=False)
        # the plan's no-grid check in the report run (a real no-grid trace seeded on each): named now, not run here
        "nogrid_report_windings": ["w044", "w048", "w055"],   # np.random.default_rng(2).choice(PLAN_REPORT, 3, ...)
        "nogrid_planes": 2,           # random-orientation planes per winding beside the moved no-grid trace
        "nogrid_size": [122, 122],    # vertices, at the reference grid step (s1-nogrid's grid)
        "fold_back_cols": 4,
        "fold_offset_vox": 1.5,
        "seed": 0,
        # w035 (the review's probe) and np.random.default_rng(3).choice(TUNE without w035, 2, replace=False)
        "whole_mesh_windings": ["w024", "w035", "w036"],
        "whole_mesh": "the reference's whole mesh (a positive of both gates); the fold and the transverse join planted "
                      "in its band rows (negatives), the fold's extra columns holes outside the band rows and the moved "
                      "block cut off from the rows above and below it by a hole row",
    },
    "aa": {
        # measured in the bar's Modal job, not here: the bar tracer run twice on each winding
        "windings": ["w027", "w028", "w031", "w032", "w034"],   # np.random.default_rng(0).choice(TUNE, 5, ...)
        "runs": 2,
        "statistic": "SD over the windings of the paired difference G_w(run 1) - G_w(run 2)",
        "floor": "max(0.10, 2 SD)",
    },
    "split": {"tune": TUNE, "report": PLAN_REPORT, "excluded": ["w045", "w046"],
              "note": "choices on w023 to w040; the report windings are scored once, under a committed run rule"},
}

GRULES = {1: GRULE_V1, 2: GRULE}

CONTROL_KEYS = ("band", "half_step", "seam", "transverse", "confetti", "fold", "nogrid", "whole")


class GError(sb.BenchError):
    pass


def grule_digest(grule=None):
    return sb.digest(GRULE if grule is None else grule)


GRULE_DIGEST = grule_digest()
GRULE_V1_DIGEST = grule_digest(GRULE_V1)


def _windowed(grule):
    """Version 2 and later: the gates are window rates and the whole-mesh controls run."""
    return "window" in grule


def run_rule(man, grule=None):
    """The rule a score is reported under: GRULE, surfbench's rule and the manifest. A report run needs its digest
    committed and passed as `frozen`."""
    return {"kind": "kit-surfbench-gscore-rule", "gscore_rule": grule or GRULE,
            "surfbench_rule_digest": sb.RULE_DIGEST, "manifest_digest": man["digest"]}


def _np():
    return sb._np()


CM2 = (sb.VOXEL_UM * 1e-4) ** 2


# ---------------------------------------------------------------- the band and the labels

def band_select(ref, band=None):
    """The labeled vertices of a reference in the band."""
    band = band or GRULE["band_z"]
    z = ref.xyz[..., 2]
    return ref.labelled() & (z >= band[0]) & (z < band[1])


def band_rows(ref, band=None):
    """Rows of the reference's grid that hold a labeled vertex in the band (rows follow z on these meshes)."""
    np = _np()
    rows = np.flatnonzero(band_select(ref, band).any(1))
    return slice(int(rows.min()), int(rows.max()) + 1) if rows.size else None


def label(xyz, valid, refs, rule=None, workers=2):
    """surfbench's d = 4 labels in control mode (masks on, no seating) and its measures of the whole surface."""
    rule = rule or sb.RULE
    near = sb.near_refs(xyz[valid], refs)
    if not near:
        return None
    summary, internal = sb._evaluate(xyz, valid, near, rule, "control", workers)
    internal["near"] = near
    return summary, internal


def _torn(xyz, valid, factor):
    """(horizontal (H, W-1), vertical (H-1, W)) edges longer than factor median edges, and the median edge."""
    np = _np()
    eh = np.linalg.norm(xyz[:, 1:] - xyz[:, :-1], axis=-1)
    ev = np.linalg.norm(xyz[1:] - xyz[:-1], axis=-1)
    vh, vv = valid[:, 1:] & valid[:, :-1], valid[1:] & valid[:-1]
    el = np.concatenate([eh[vh], ev[vv]])
    med = float(np.median(el)) if el.size else float("nan")
    if not math.isfinite(med):
        return np.zeros(eh.shape, bool), np.zeros(ev.shape, bool), med
    return vh & (eh > factor * med), vv & (ev > factor * med), med


# ---------------------------------------------------------------- reach

def _runs(idx, code, torn_h, torn_v, bridge):
    """Consecutive labeled vertices along grid rows and columns that a run joins: nothing between them is a hole,
    a vertex outside every reference or a torn edge, and at most `bridge` of them are off every winding or over a
    gap (no-reference vertices between are free). code: 0 ends a run, 1 labeled, 2 counted, 3 free. Returns
    (q1, q2, axis, line, p1, p2)."""
    np = _np()
    out = {k: [] for k in ("q1", "q2", "axis", "line", "p1", "p2")}
    for axis, G, T in ((1, idx, torn_h), (0, idx.T, torn_v.T)):
        C = code if axis == 1 else code.T
        for li in range(G.shape[0]):
            c = C[li]
            pos = np.flatnonzero(c == 1)
            if len(pos) < 2:
                continue
            ends = np.cumsum(c == 0)
            cnt = np.cumsum(c == 2)
            tc = np.concatenate([[0], np.cumsum(T[li])])
            p1, p2 = pos[:-1], pos[1:]
            ok = (ends[p2] == ends[p1]) & (cnt[p2] - cnt[p1] <= bridge) & (tc[p2] == tc[p1])
            if not ok.any():
                continue
            p1, p2 = p1[ok], p2[ok]
            out["q1"].append(G[li, p1])
            out["q2"].append(G[li, p2])
            out["p1"].append(p1)
            out["p2"].append(p2)
            out["axis"].append(np.full(len(p1), axis, np.int8))
            out["line"].append(np.full(len(p1), li, np.int64))
    if not out["q1"]:
        z = np.zeros(0, np.int64)
        return z, z, z.astype(np.int8), z, z, z
    return tuple(np.concatenate(out[k]) for k in ("q1", "q2", "axis", "line", "p1", "p2"))


def _switch_test(q1, q2, l1, l2, axis, line, p1, p2, idx, S, IN, J, near, rule):
    """surfbench's switch test for label changes between two labeled vertices: a switch when, at either end, the
    other end's winding is present (inside its footprint) and more than coincide_vox away, unless the two references
    meet (one has the other within coincide_vox, from the manifest) at a vertex along the crossing. Returns
    (switch, contact) boolean arrays."""
    np = _np()
    apart = rule["references"]["coincide_vox"]
    contact_d = rule["references"]["contact_vox"]
    row_of = {r.gid: i for i, r in enumerate(near)}
    r1 = np.array([row_of.get(int(x), -1) for x in l1], dtype=np.int64)
    r2 = np.array([row_of.get(int(x), -1) for x in l2], dtype=np.int64)
    s12 = np.where(r1 >= 0, np.abs(S[np.maximum(r1, 0), q2]), np.inf)
    i12 = (r1 >= 0) & IN[np.maximum(r1, 0), q2]
    s21 = np.where(r2 >= 0, np.abs(S[np.maximum(r2, 0), q1]), np.inf)
    i21 = (r2 >= 0) & IN[np.maximum(r2, 0), q1]
    sw = (i12 & (s12 > apart)) | (i21 & (s21 > apart))
    for t in np.flatnonzero(sw):
        if r1[t] < 0 or r2[t] < 0:
            continue
        grid_line = idx[line[t]] if axis[t] == 1 else idx[:, line[t]]
        path = grid_line[p1[t]:p2[t] + 1]
        path = path[path >= 0]
        for ra, gb in ((r1[t], l2[t]), (r2[t], l1[t])):
            at = near[ra].attrs
            if "g_pos" not in at:
                continue
            jv = J[ra, path][IN[ra, path]]
            met = (((at["lab_pos"].ravel()[jv] == gb) & (at["g_pos"].ravel()[jv] <= apart)) |
                   ((at["lab_neg"].ravel()[jv] == gb) & (at["g_neg"].ravel()[jv] <= apart)))
            if met.any():
                sw[t] = False
                break
    contact = sw & ((i12 & (s12 <= contact_d)) | (i21 & (s21 <= contact_d)))
    return sw, contact


def reach_graph(xyz, valid, internal, rule=None, grule=None):
    """Regions (runs of one winding) and the components they form through seam links. Returns a dict: comp (per
    vertex of the surface, -1 when not labeled), region (per vertex), link counts, torn edges."""
    np = _np()
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    rule, grule = rule or sb.RULE, grule or GRULE
    G = grule["reach"]
    idx = internal["idx"]
    cls, lab, _ = internal["d4"]
    S, IN, J, near = internal["S"], internal["IN"], internal["J"], internal["near"]
    N = len(cls)
    code = np.zeros(valid.shape, np.int8)
    v = idx >= 0
    cv = cls[idx[v]]
    cc = np.zeros(cv.shape, np.int8)
    cc[cv == sb.ON] = 1
    cc[(cv == sb.OFF) | (cv == sb.GAP)] = 2
    cc[cv == sb.NOREFC] = 3
    code[v] = cc                                     # OUTSIDE and holes end a run (0)
    torn_h, torn_v, med = _torn(xyz, valid, G["tear_factor"])
    q1, q2, axis, line, p1, p2 = _runs(idx, code, torn_h, torn_v, G["bridge_vertices"])
    l1, l2 = lab[q1], lab[q2]
    same = l1 == l2
    on = cls == sb.ON
    n_on = int(on.sum())
    ids = np.full(N, -1, np.int64)
    ids[on] = np.arange(n_on)
    if n_on == 0:
        return {"comp": np.full(N, -1), "region": np.full(N, -1), "regions": 0, "components": 0,
                "links": {}, "torn_edges": int(torn_h.sum() + torn_v.sum()), "median_edge_vox": med}
    a, b = ids[q1[same]], ids[q2[same]]
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(n_on, n_on))
    nreg, reg_on = connected_components(g, directed=False)
    region = np.full(N, -1, np.int64)
    region[on] = reg_on
    d = ~same
    sw, ct = _switch_test(q1[d], q2[d], l1[d], l2[d], axis[d], line[d], p1[d], p2[d], idx, S, IN, J, near, rule)
    ra, rb = region[q1[d]], region[q2[d]]
    lo, hi = np.minimum(ra, rb), np.maximum(ra, rb)
    key = lo * nreg + hi
    nb = {}
    ns = {}
    for k, s in zip(key.tolist(), sw.tolist()):
        if s:
            ns[k] = ns.get(k, 0) + 1
        else:
            nb[k] = nb.get(k, 0) + 1
    linked = [k for k in nb if nb[k] > ns.get(k, 0)]
    la = np.array([k // nreg for k in linked], dtype=np.int64)
    lb = np.array([k % nreg for k in linked], dtype=np.int64)
    rg = coo_matrix((np.ones(len(la)), (la, lb)), shape=(nreg, nreg))
    ncomp, reg_comp = connected_components(rg, directed=False)
    comp = np.full(N, -1, np.int64)
    comp[on] = reg_comp[reg_on]
    return {"comp": comp, "region": region, "regions": int(nreg), "components": int(ncomp),
            "links": {"region_pairs": len(set(nb) | set(ns)), "linked_pairs": len(linked),
                      "boundary_crossings": int((~sw).sum()), "switch_crossings": int(sw.sum()),
                      "switch_crossings_contact": int(ct.sum())},
            "torn_edges": int(torn_h.sum() + torn_v.sum()), "median_edge_vox": _r(med, 3)}


def _r(x, n=4):
    return sb._r(x, n)


def seed_vertex(xyz, valid, internal, graph, seed=None, seed_rc=None, grule=None):
    """The surface vertex a seed starts from (index into the surface's valid vertices) and how it was found: the
    nearest valid vertex to the seed point (or the given grid vertex); when it lies on no winding, the nearest
    labeled vertex within seed_radius_vertices grid steps. None when there is none."""
    np = _np()
    grule = grule or GRULE
    idx = internal["idx"]
    cls = internal["d4"][0]
    if seed_rc is not None:
        r, c = int(seed_rc[0]), int(seed_rc[1])
        if not valid[r, c]:
            return None, {"reason": "the seed vertex is a hole"}
    else:
        P = np.where(valid[..., None], xyz, np.inf)
        d = np.linalg.norm(P - np.asarray(seed, float)[None, None, :], axis=-1)
        r, c = np.unravel_index(int(np.argmin(d)), d.shape)
    info = {"vertex_rc": [int(r), int(c)], "seed_distance_vox": (None if seed is None else _r(float(
        np.linalg.norm(xyz[r, c] - np.asarray(seed, float))), 2))}
    q = int(idx[r, c])
    if cls[q] == sb.ON:
        info["on"] = True
        return q, info
    rad = int(grule["reach"]["seed_radius_vertices"])
    H, W = valid.shape
    r0, r1, c0, c1 = max(0, r - rad), min(H, r + rad + 1), max(0, c - rad), min(W, c + rad + 1)
    sub = idx[r0:r1, c0:c1]
    ok = sub >= 0
    ok[ok] = cls[sub[ok]] == sb.ON
    if not ok.any():
        info["on"] = False
        info["reason"] = f"no labeled vertex within {rad} grid steps of the seed"
        return None, info
    rr, cc_ = np.nonzero(ok)
    cheb = np.maximum(np.abs(rr + r0 - r), np.abs(cc_ + c0 - c))
    eu = np.linalg.norm(xyz[rr + r0, cc_ + c0] - xyz[r, c], axis=-1)
    k = np.lexsort((eu, cheb))[0]
    info.update({"on": False, "moved_to_rc": [int(rr[k] + r0), int(cc_[k] + c0)], "moved_steps": int(cheb[k])})
    return int(sub[rr[k], cc_[k]]), info


# ---------------------------------------------------------------- credit

def _masked_candidate(xyz, valid, mask, rule):
    """A candidate surface whose scoring points are only the dense points between vertices of `mask` (normals from
    the whole surface)."""
    np = _np()
    cand = sb.Ref("candidate", -10, xyz, valid, rule)
    up, uv, src = sb.upsample(xyz, valid, cand.k)
    un, _, uok, ustep = sb.grid_geometry(up, uv)
    _, mv, _ = sb.upsample(xyz, valid & mask, cand.k)
    keep = uok & mv
    if not math.isfinite(ustep):
        ustep = cand.step / max(cand.k, 1) if math.isfinite(cand.step) else 1.0
    cand._pts = (up[keep], un[keep], src[keep], ustep)
    return cand


def coverage(ref, xyz, valid, mask, rule=None, grule=None, workers=2):
    """(covered (bool over the reference's band vertices), band selection, band area cm2): which of the reference's
    labeled band vertices lie within credit_vox of the surface's vertices in `mask` (point to plane, inside the
    footprint, as surfbench's recall)."""
    np = _np()
    rule, grule = rule or sb.RULE, grule or GRULE
    sel = band_select(ref, grule["band_z"])
    band_cm2 = float(ref.area[sel].sum()) * CM2
    if not sel.any() or not mask.any():
        return np.zeros(int(sel.sum()), bool), sel, band_cm2
    cand = _masked_candidate(xyz, valid, mask, rule)
    if len(cand.scoring()[0]) == 0:
        return np.zeros(int(sel.sum()), bool), sel, band_cm2
    s, ins, _, _ = sb.match(ref.xyz[sel], cand, workers)
    return ins & (np.abs(s) <= grule["credit_vox"]), sel, band_cm2


def credit(xyz, valid, internal, graph, target, refs, seed_q=None, rule=None, grule=None, workers=2):
    """G_w for one target reference: the reached part is the seed's component, or (seed_q None) the component that
    holds the most of the surface's area labeled w in the band. Returns the record."""
    np = _np()
    rule, grule = rule or sb.RULE, grule or GRULE
    cls, lab, _ = internal["d4"]
    idx = internal["idx"]
    comp = graph["comp"]
    P = xyz[valid]
    _, area, _, _ = sb.grid_geometry(xyz, valid)
    varea = area[valid] * CM2
    z = P[:, 2]
    band = grule["band_z"]
    inband = (z >= band[0]) & (z < band[1])
    on = cls == sb.ON
    g = target.gid
    mine = on & (lab == g)
    rec = {"winding": target.name}
    def cover(c):
        reached = (comp == c) & on if c >= 0 else np.zeros(len(cls), bool)
        m = np.zeros(valid.shape, bool)
        m[valid] = reached & (lab == g)
        return (reached,) + coverage(target, xyz, valid, m, rule, grule, workers)

    if seed_q is not None:
        c = int(comp[seed_q]) if seed_q >= 0 else -1
        rec["reached_from"] = "seed"
        reached, cov, sel, band_cm2 = cover(c)
    else:
        cand = mine & inband & (comp >= 0)
        rec["reached_from"] = ("of the components with the most area on this winding in the band, the one credited "
                               "most")
        if cand.any():
            w = np.bincount(comp[cand], weights=varea[cand])
            order = [int(k) for k in np.argsort(-w, kind="stable")[:int(grule["reach"]["best_components"])]
                     if w[k] >= grule["reach"]["best_min_share"] * w.max()]
            best = None
            for k in order:
                got = cover(k)
                key = float(target.area[got[2]][got[1]].sum()) if got[1].size else 0.0
                if best is None or key > best[0]:
                    best = (key, k, got)
            c = best[1]
            reached, cov, sel, band_cm2 = best[2]
        else:
            c = -1
            reached, cov, sel, band_cm2 = cover(c)
    covered_cm2 = float(target.area[sel][cov].sum()) * CM2 if cov.size else 0.0
    other = on & (lab != g)
    wrong = other & ~reached & inband
    seam = other & reached & inband
    rec.update({
        "G": _r(covered_cm2 / band_cm2) if band_cm2 > 0 else None,
        "covered_cm2": _r(covered_cm2, 3), "band_cm2": _r(band_cm2, 3),
        "wrong_cm2": _r(float(varea[wrong].sum()), 3),
        "net_cm2": _r(covered_cm2 - float(varea[wrong].sum()), 3),
        "seam_cm2": _r(float(varea[seam].sum()), 3),
        "off_cm2": _r(float(varea[(cls == sb.OFF) & inband].sum()), 3),
        "unreached_own_cm2": _r(float(varea[mine & ~reached & inband].sum()), 3),
        "reached_own_cm2": _r(float(varea[mine & reached].sum()), 3),
        "surface_band_cm2": _r(float(varea[inband].sum()), 3),
        "component": c,
    })
    return rec


# ---------------------------------------------------------------- gates

def _write_temp(xyz, valid, folder):
    return sb.write_tifxyz(Path(folder), xyz, valid,
                           {"format": "tifxyz", "type": "seg", "scale": [0.05, 0.05], "uuid": Path(folder).name})


def _census(surface, tools, threads=2):
    """VC3D's transverse self-contact census of a tifxyz: {"count", "sites": [[x, y, z], ...]} (every contact on
    both quad diagonals, as kit's check_surface sums them), or None."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        rep = Path(tmp) / "selfcross.json"
        try:
            subprocess.run(tools.argv("vc_tifxyz_selfcross", "--surface", surface, "-o", rep, "--threads", threads),
                           capture_output=True, timeout=1800, check=False)
            sc = json.loads(rep.read_text())
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return None
    census = sc.get("census", [])
    sites = [[round(float(v), 2) for v in c["site"]] for d in census for c in d.get("transverse_contacts", [])]
    count = sum(int(d.get("transverse", 0)) for d in census)
    return {"count": count, "sites": sites if len(sites) == count else None}


def vc3d_counter(tools=None, threads=2):
    """A self-crossing counter on VC3D's vc_tifxyz_selfcross: f(xyz, valid, path=None) -> {"count", "sites"}, or
    None when the tool is not found. Test counters may return a bare count."""
    tools = sb._find_tools(tools)
    if tools is None or not tools.has("vc_tifxyz_selfcross"):
        return None

    def count(xyz, valid, path=None):
        if path is not None:
            return _census(path, tools, threads)
        with tempfile.TemporaryDirectory() as tmp:
            return _census(_write_temp(xyz, valid, Path(tmp) / "surface"), tools, threads)

    return count


def _counted(counter, xyz, valid, path=None):
    """(count, sites or None) from a counter that returns a count or {"count", "sites"}."""
    if counter is None:
        return None, None
    out = counter(xyz, valid, path)
    if out is None:
        return None, None
    if isinstance(out, dict):
        return out.get("count"), out.get("sites")
    return int(out), None


def surface_rates(summary, xyz, valid, counter, path=None):
    """(switch line per scored cm2, self-crossings and their rate per cm2 of a labeled surface; the contact sites
    when the counter gives them, else None)."""
    sw = summary.get("switches", {}).get("switch_line_cm_per_cm2")
    n, sites = _counted(counter, xyz, valid, path)
    area = summary.get("area_cm2") or 0.0
    out = {"switch_line_cm_per_cm2": sw, "switch_crossings": summary.get("switches", {}).get("switch_crossings"),
           "selfcross": n, "transverse_per_cm2": (_r(n / area, 3) if n is not None and area > 0 else None),
           "area_cm2": summary.get("area_cm2")}
    return out, sites


def explained(sites, ref_sites, d):
    """How many of a surface's contacts are the references' own: those within d voxels of a reference contact, at
    most as many as the reference contacts within d of one of the surface's."""
    np = _np()
    if not sites or not ref_sites:
        return 0
    from scipy.spatial import cKDTree
    a, b = np.asarray(sites, float), np.asarray(ref_sites, float)
    na = int(np.isfinite(cKDTree(b).query(a, distance_upper_bound=d)[0]).sum())
    nb = int(np.isfinite(cKDTree(a).query(b, distance_upper_bound=d)[0]).sum())
    return min(na, nb)


def explain_sites(sites, ref_sites, d):
    """Version 2: which of a surface's contact sites are the references' own, one to one: a maximum matching of the
    surface's sites to reference sites within d voxels (each reference site excuses at most one). Boolean per site."""
    np = _np()
    a = np.asarray(sites if sites else np.zeros((0, 3)), float).reshape(-1, 3)
    b = np.asarray(ref_sites if ref_sites else np.zeros((0, 3)), float).reshape(-1, 3)
    out = np.zeros(len(a), bool)
    if not len(a) or not len(b):
        return out
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching
    from scipy.spatial import cKDTree
    near = cKDTree(a).query_ball_tree(cKDTree(b), d)
    rows = np.repeat(np.arange(len(a)), [len(n) for n in near])
    cols = np.array([j for n in near for j in sorted(n)], dtype=np.int64)
    if not len(cols):
        return out
    m = csr_matrix((np.ones(len(cols)), (rows, cols)), shape=(len(a), len(b)))
    return maximum_bipartite_matching(m, perm_type="column") >= 0


def _window_sums(a, kr, kc):
    """Sums of `a` over every kr x kc window of the grid (top-left corner at each position)."""
    np = _np()
    H, W = a.shape
    S = np.zeros((H + 1, W + 1))
    S[1:, 1:] = np.cumsum(np.cumsum(a, 0), 1)
    return S[kr:, kc:] - S[:-kr, kc:] - S[kr:, :-kc] + S[:-kr, :-kc]


def window_max(amount, denom, k, share):
    """The largest amount / denominator over k x k windows of a grid at every position (k cut to the grid's size),
    among windows whose denominator is at least `share` of the largest window's. Returns {"rate", "at" (top-left
    vertex), "amount", "area_cm2", "window", "windows"}; the rate is 0 when the denominator and the amount are 0
    everywhere, None when only the denominator is."""
    np = _np()
    H, W = amount.shape
    kr, kc = max(1, min(k, H)), max(1, min(k, W))
    rec = {"window": [kr, kc]}
    SA = _window_sums(np.asarray(denom, float), kr, kc)
    SD = np.maximum(_window_sums(np.asarray(amount, float), kr, kc), 0.0)
    amax = float(SA.max()) if SA.size else 0.0
    if amax <= 0:
        rec.update({"rate": 0.0 if float(np.sum(amount)) <= 0 else None, "at": None, "amount": None,
                    "area_cm2": 0.0, "windows": 0})
        return rec
    ok = SA >= share * amax
    R = np.where(ok, SD / np.where(ok, SA, 1.0), -1.0)
    i = int(np.argmax(R))
    r0, c0 = divmod(i, R.shape[1])
    rec.update({"rate": _r(float(R.flat[i]), 4), "at": [int(r0), int(c0)], "amount": _r(float(SD.flat[i]), 4),
                "area_cm2": _r(float(SA.flat[i]), 4), "windows": int(ok.sum())})
    return rec


def window_rates(xyz, valid, internal, sites, n, ref_sites, grule, ref_sites_known=True):
    """Version 2's gate rates: the largest switch line per scored cm2 and the largest count of contacts that are not
    the references' per cm2, each over the rule's windows. Returns a record with "switch_window_max" and
    "selfcross_window_max" (None, with "selfcross_unmeasured" saying why, when the contacts cannot be placed or
    excused)."""
    np = _np()
    Wn = grule["window"]
    _, area, _, step = sb.grid_geometry(xyz, valid)
    k = max(2, int(math.ceil(Wn["side_vox"] / step))) if math.isfinite(step) and step > 0 else 2
    A = area * CM2
    cls = internal["d4"][0]
    rc = np.argwhere(valid)                       # row-major, as the surface's valid vertices are numbered
    scored = np.zeros(valid.shape, bool)
    scored[valid] = (cls == sb.ON) | (cls == sb.OFF)
    out = {"window_vertices": k, "median_edge_vox": _r(step, 3)}
    # switch line: surfbench's switch crossings, one median edge of line each (as its switch_line_cm), half at each end
    step_cm = (step if math.isfinite(step) else 0.0) * sb.VOXEL_UM * 1e-4
    pairs = internal.get("switch_pairs")
    amt = np.zeros(valid.shape)
    if pairs is not None and len(pairs):
        for end in (0, 1):
            r, c = rc[pairs[:, end]].T
            np.add.at(amt, (r, c), 0.5 * step_cm)
    out["switch"] = window_max(amt, np.where(scored, A, 0.0), k, Wn["min_area_share"])
    out["switch"]["crossings"] = int(len(pairs)) if pairs is not None else None
    out["switch_window_max"] = out["switch"]["rate"]
    # self-crossings: the contacts that are not the references', at their nearest vertex
    amt = np.zeros(valid.shape)
    sc = {"contacts": n}
    why = None
    if n is None:
        why = "no self-crossing count for the surface (vc_tifxyz_selfcross failed or timed out)"
    elif n > 0 and sites is None:
        why = "the self-crossing counter gave no contact sites, so the contacts cannot be placed or excused"
    elif n > 0 and not ref_sites_known:
        why = "a scored reference's own contacts are not known, so none can be excused"
    elif n > 0:
        ex = explain_sites(sites, ref_sites, grule["gates"]["selfcross"]["explain_vox"])
        sc.update({"references_own": int(ex.sum()), "not_references": int((~ex).sum())})
        un = np.asarray(sites, float).reshape(-1, 3)[~ex]
        if len(un):
            from scipy.spatial import cKDTree
            _, j = cKDTree(xyz[valid]).query(un)
            r, c = rc[j].T
            np.add.at(amt, (r, c), 1.0)
    if why is None:
        sc.update(window_max(amt, A, k, Wn["min_area_share"]))
    else:
        sc.update({"rate": None, "unmeasured": why})
    out["selfcross"] = sc
    out["selfcross_window_max"] = sc["rate"]
    out["selfcross_unmeasured"] = why
    return out


def reference_rates(ref, refs, refs_dir, man, counter, rule=None, cache_dir=None, workers=2):
    """The reference's own rates: its whole mesh labeled and counted as a candidate would be. Cached per manifest
    and surfbench rule under cache_dir."""
    rule = rule or sb.RULE
    key = f"{ref.name}-{man['digest'][:12]}-{sb.rule_digest(rule)[:12]}-sites.json"
    cache = Path(cache_dir) / "reference-rates" / key if cache_dir else None
    if cache is not None and cache.is_file():
        rec = json.loads(cache.read_text())
        if (rec.get("selfcross") is not None and "sites" in rec) or counter is None:
            return rec
    lab = label(ref.xyz, ref.valid, refs, rule, workers)
    summary = lab[0]
    rec_m = next(x for x in man["references"] if x["name"] == ref.name)
    p = Path(rec_m["path"])
    p = p if p.is_absolute() else Path(refs_dir) / p
    rates, sites = surface_rates(summary, ref.xyz, ref.valid, counter, p if p.is_dir() else None)
    rec = {"reference": ref.name, **rates, "sites": sites}
    if cache is not None and rec.get("selfcross") is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rec))
    return rec


def apply_gates(rates, ref_rates, grule=None, local=None):
    """Each gate: the surface's rate minus the reference's, against the frozen threshold. `local` overrides a
    reference rate by metric (the self-crossing gate's rate under the surface). pass is None when the threshold is
    not frozen or a rate is missing."""
    grule = grule or GRULE
    out = {}
    for k, gd in grule["gates"].items():
        m = gd["metric"]
        a, b = rates.get(m), (local or {}).get(m, ref_rates.get(m))
        ex = None if a is None or b is None else a - b
        t = gd["threshold"]
        out[k] = {"rate": a, "reference_rate": b, "excess": _r(ex, 4), "threshold": t,
                  "pass": None if ex is None or t is None else bool(ex <= t + 1e-12)}
    vals = [g["pass"] for g in out.values()]
    out["pass"] = None if any(v is None for v in vals) else all(vals)
    return out


# ---------------------------------------------------------------- scoring one surface

def score_grid(xyz, valid, targets, refs, man, refs_dir=None, seed=None, seed_rc=None, best=False, counter=None,
               rule=None, grule=None, cache_dir=None, workers=2, path=None, ref_rates=None, seed_source=None):
    """G_w, the gates and net area of a surface grid for each target reference (Ref objects). The reached part grows
    from the seed (a point or a grid vertex); with best, the best component per winding; with neither, nothing is
    reached and G_w is 0."""
    rule, grule = rule or sb.RULE, grule or GRULE
    lab = label(xyz, valid, refs, rule, workers)
    out = {"vertices": int(valid.sum())}
    if lab is None:
        out.update({"windings": {t.name: {"winding": t.name, "G": 0.0, "credit": 0.0, "reason": "the surface lies "
                                          "outside every reference"} for t in targets},
                    "gates": None})
        return out
    summary, internal = lab
    graph = reach_graph(xyz, valid, internal, rule, grule)
    out.update({"area_cm2": summary["area_cm2"], "scored_share_d4": summary["d4"]["scored_share"],
                "label_shares_d4": summary["d4"]["label_shares"],
                "reach": {k: graph[k] for k in ("regions", "components", "links", "torn_edges", "median_edge_vox")}})
    seed_q = None
    if best:
        out["seed"] = {"point": None, "source": "best", "mode": "best component per winding"}
    elif seed is not None or seed_rc is not None:
        seed_q, info = seed_vertex(xyz, valid, internal, graph, seed, seed_rc, grule)
        src = seed_source or ("point" if seed is not None else "grid vertex")
        out["seed"] = {"point": None if seed is None else [float(v) for v in seed], "source": src, **info}
        if seed_q is None:
            seed_q = -1
    else:
        seed_q = -1                                      # never the best component silently: nothing is reached
        out["seed"] = {"point": None, "source": "none",
                       "reason": "no seed (none given and none in the trace's meta.json), so nothing is reached and "
                                 "G_w is 0"}
    rates, sites = surface_rates(summary, xyz, valid, counter, path)
    out["rates"] = rates
    out["windings"] = {}
    rrs = {}
    for t in targets:
        rr = (ref_rates or {}).get(t.name)
        if rr is None and refs_dir is not None:
            rr = reference_rates(t, refs, refs_dir, man, counter, rule, cache_dir, workers)
        rrs[t.name] = rr or {}
    # the self-crossing gate's reference: the surface's contacts that are the scored references' own
    refs_known = all(rrs[t.name].get("selfcross") is not None for t in targets)
    known = rates.get("selfcross") is not None and refs_known
    ref_sites = [p for t in targets for p in (rrs[t.name].get("sites") or [])]
    own = explained(sites, ref_sites, grule["gates"]["selfcross"]["explain_vox"]) if known else None
    area = summary.get("area_cm2") or 0.0
    local = {"transverse_per_cm2": _r(own / area, 3) if known and area > 0 else None}
    rates["references_own_contacts"] = own
    windowed = _windowed(grule)
    if windowed:
        sites_known = refs_known and all(not rrs[t.name]["selfcross"] or rrs[t.name].get("sites") is not None
                                         for t in targets)
        win = window_rates(xyz, valid, internal, sites, rates.get("selfcross"), ref_sites, grule, sites_known)
        out["windows"] = {k: win[k] for k in ("window_vertices", "median_edge_vox", "switch", "selfcross")}
        rates["switch_window_max"] = win["switch_window_max"]
        rates["selfcross_window_max"] = win["selfcross_window_max"]
        if win["selfcross_unmeasured"]:
            rates["selfcross_unmeasured"] = win["selfcross_unmeasured"]
    for t in targets:
        rec = credit(xyz, valid, internal, graph, t, refs, seed_q, rule, grule, workers)
        rr = rrs[t.name]
        if windowed:
            # the switch gate's reference rate is the reference's whole-mesh rate; the self-crossing rate already
            # leaves out the references' own contacts
            gates = apply_gates(rates, rr, grule, {"switch_window_max": rr.get("switch_line_cm_per_cm2"),
                                                   "selfcross_window_max": 0.0})
            sw0, ref0 = rates.get("switch_line_cm_per_cm2"), rr.get("switch_line_cm_per_cm2")
            sc0, own0 = rates.get("transverse_per_cm2"), local["transverse_per_cm2"]
            rec["whole_surface_excess"] = {      # version 1's gate rates, for comparison (not gates here)
                "switch": None if sw0 is None or ref0 is None else _r(sw0 - ref0, 4),
                "selfcross": None if sc0 is None or own0 is None else _r(sc0 - own0, 4)}
        else:
            gates = apply_gates(rates, rr, grule, local)
        rec["gates"] = gates
        rec["credit"] = (None if gates["pass"] is None else (rec["G"] if gates["pass"] else 0.0))
        out["windings"][t.name] = rec
    return out


def _read_seed(surface):
    p = Path(surface) / "meta.json"
    if p.is_file():
        try:
            s = json.loads(p.read_text()).get("seed")
        except json.JSONDecodeError:
            return None
        if isinstance(s, list) and len(s) == 3:
            return [float(v) for v in s]
    return None


def score(surface, windings=None, refs_dir=sb.DEFAULT_REFS, seed=None, best=False, counter="vc3d", rule=None,
          grule=None, cache_dir=None, workers=2, frozen=None, log=None):
    """Score one tifxyz for its winding(s): G_w with the reached part from its seed (the given point, else the
    "seed" in its meta.json; with neither, G_w is 0; `best` instead takes the best component per winding), the gates
    and net area. Windings default to the winding its seed lies on. A report winding takes its seed only from the
    trace's meta.json, under the current rule version, and needs `frozen`, the committed digest of the run rule."""
    np = _np()
    rule, grule = rule or sb.RULE, grule or GRULE
    if seed is not None and best:
        raise GError("a seed point and best exclude each other")
    t0 = time.time()
    man, refs = sb.load_refs(refs_dir, rule)
    au = sb.load_audit(refs_dir, man, rule)
    rr = run_rule(man, grule)
    rdig = sb.digest(rr)
    by = {r.name: r for r in refs}
    xyz, valid, _ = sb.read_tifxyz(surface)
    if not valid.any():
        raise GError(f"{surface}: no valid vertices")
    source = "argument" if seed is not None else None
    if seed is None and not best:
        seed = _read_seed(surface)
        source = "meta.json" if seed is not None else None
    if counter == "vc3d":
        counter = vc3d_counter(threads=workers)
    out = {"kind": "kit-surfbench-gscore", "surface": str(surface), "refs": str(refs_dir),
           "gscore_rule_digest": grule_digest(grule), "run_rule_digest": rdig, "surfbench_rule_digest":
           sb.rule_digest(rule), "manifest_digest": man["digest"], "audit_digest": au.get("digest") if au else None,
           "invalid_reasons": []}
    if windings:
        missing = [w for w in windings if w not in by]
        if missing:
            raise GError(f"no reference named {missing}")
        names = list(windings)
    else:
        lab = label(xyz, valid, refs, rule, workers)
        if lab is None:
            raise GError(f"{surface}: the surface lies outside every reference; name its winding with --winding")
        _, internal = lab
        graph = reach_graph(xyz, valid, internal, rule, grule)
        if seed is None:
            raise GError(f"{surface}: no seed in its meta.json; name its winding with --winding (and use --best)")
        q, info = seed_vertex(xyz, valid, internal, graph, seed, None, grule)
        if q is None:
            raise GError(f"{surface}: {info.get('reason')}; name its winding with --winding")
        gid = int(internal["d4"][1][q])
        names = [next(r.name for r in refs if r.gid == gid)]
    report = [w for w in names if w in grule["split"]["report"]]
    if report and (best or source == "argument"):
        raise GError(f"{report} are report windings: their seed comes only from the trace's meta.json (no --seed, "
                     "no --best)")
    if report and grule.get("version") != GRULE["version"]:
        raise GError(f"{report} are report windings: score them only under the current rule version "
                     f"({GRULE['version']})")
    if report and frozen != rdig:
        raise GError(f"{report} are report windings: score them only under the committed run rule (--frozen "
                     f"{rdig}), once, with the candidate named before the run")
    res = score_grid(xyz, valid, [by[w] for w in names], refs, man, refs_dir, seed=seed, best=best, counter=counter,
                     rule=rule, grule=grule, cache_dir=cache_dir, workers=workers, path=surface, seed_source=source)
    out.update(res)
    out["gscore_rule_version"] = grule.get("version")
    out["split"] = {w: ("report" if w in grule["split"]["report"] else "tune" if w in grule["split"]["tune"]
                        else "excluded" if w in grule["split"]["excluded"] else "buffer") for w in names}
    if counter is None:
        out["invalid_reasons"].append("vc_tifxyz_selfcross not found (set VC_BIN): the self-crossing gate is unmeasured")
    if any(g["threshold"] is None for g in grule["gates"].values()):
        out["invalid_reasons"].append("gate thresholds not frozen (python -m kit surfbench gscore --controls)")
    out["invalid_reasons"] += unmeasured_reasons(out)
    out["valid"] = not out["invalid_reasons"]
    out["seconds"] = round(time.time() - t0, 1)
    _ = np
    return out


def unmeasured_reasons(res):
    """A reason for each gate of each winding that has a threshold but no excess: its rate or the reference's could
    not be measured (a self-crossing tool that failed or timed out on the surface or on a reference's whole mesh,
    contacts without sites, no scored area). Such a score is invalid, never a pass."""
    out = []
    rates = res.get("rates") or {}
    for name, w in (res.get("windings") or {}).items():
        for k, g in (w.get("gates") or {}).items():
            if not isinstance(g, dict) or g.get("threshold") is None or g.get("excess") is not None:
                continue
            if k == "selfcross" and rates.get("selfcross") is None:
                why = "no self-crossing count for the surface (vc_tifxyz_selfcross failed, timed out or is missing)"
            elif k == "selfcross" and rates.get("selfcross_unmeasured"):
                why = rates["selfcross_unmeasured"]
            elif g.get("reference_rate") is None:
                why = f"no {k} rate for {name}'s whole mesh"
            else:
                why = f"no {k} rate for the surface"
            out.append(f"{name}: the {k} gate was not measured ({why})")
    return out


# ---------------------------------------------------------------- planted controls

def band_surface(ref, band=None):
    """The reference's own grid over its band rows: the perfect surface for its winding in the band."""
    sl = band_rows(ref, band)
    if sl is None:
        return None
    return ref.xyz[sl].copy(), ref.valid[sl].copy(), ref.normals[sl].copy(), sl


def band_seed_rc(ref, sl, band=None):
    """The grid vertex (in band-surface rows) used as the seed of a band surface: a labeled band vertex nearest the
    band's middle z, then nearest the grid's middle column."""
    np = _np()
    band = band or GRULE["band_z"]
    sel = band_select(ref, band)[sl]
    rc = np.argwhere(sel)
    zmid = 0.5 * (band[0] + band[1])
    z = ref.xyz[sl][..., 2][sel]
    k = np.lexsort((np.abs(rc[:, 1] - sel.shape[1] / 2), np.round(np.abs(z - zmid) / 20.0)))[0]
    return int(rc[k, 0]), int(rc[k, 1])


def moved(xyz, valid, nrm, offset):
    """The grid moved `offset` voxels along its unit normals (holes stay holes)."""
    np = _np()
    return xyz + offset * np.nan_to_num(nrm), valid & np.isfinite(nrm).all(-1)


def _full_columns(valid, share=0.5):
    """Columns holding at least `share` of the fullest column's valid vertices (a grid's edge columns are ragged)."""
    np = _np()
    n = valid.sum(0)
    return np.flatnonzero(n >= share * max(int(n.max()), 1)) if n.size else np.zeros(0, np.int64)


def _end_on(A, B, rows, rule, workers, probe=3):
    """Which end column of A's band rows lies on B (median offset within coincide_vox, 80 % inside). Returns (end
    column, B's column there, row offset to B, the direction on B away from A, A's inward direction) or None. The
    direction away from A is the side of that column, `probe` columns off, whose vertices lie least on A (the other
    side runs over A where the two windings overlap, or leaves B's grid)."""
    np = _np()
    apart = rule["references"]["coincide_vox"]
    vc = _full_columns(A.valid[rows])
    if vc.size < 3:
        return None
    arow = np.arange(A.valid.shape[0])[rows]
    HB, WB = B.valid.shape
    for c_end, inward in ((int(vc.min()), 1), (int(vc.max()), -1)):
        sel = A.valid[rows, c_end]
        if sel.sum() < 3:
            continue
        s, ins, src, _ = sb.match(A.xyz[rows, c_end][sel], B, workers)
        if ins.mean() < 0.8 or np.median(np.abs(s[ins])) > apart:
            continue
        rr, cc = np.divmod(src[ins], WB)
        c1 = int(np.median(cc))
        dr = int(np.median(rr - arow[sel][ins]))
        rb = arow + dr
        rb = rb[(rb >= 0) & (rb < HB)]
        sides = []
        for d in (1, -1):
            col = c1 + d * probe
            if col < 0 or col >= WB or rb.size == 0:
                continue
            v = B.valid[rb, col]
            if v.sum() < 3:
                continue
            s2, ins2, _, _ = sb.match(B.xyz[rb, col][v], A, workers)
            sides.append((float((ins2 & (np.abs(s2) <= apart)).mean()), d))
        if not sides:
            continue
        sides.sort()
        if len(sides) == 2 and sides[0][0] == sides[1][0]:
            continue
        return c_end, c1, dr, sides[0][1], inward
    return None


def seam_join(A, B, rule=None, band=None, workers=2, cols=None):
    """A's band surface followed past its seam onto B: where an end of A lies on B, B's columns beyond it (away from
    the overlap) are joined to that end, rows matched by the offset at the end. Returns (xyz, valid, seed_rc,
    columns of the B part, joint edge lengths) or None when no end of A lies on B."""
    np = _np()
    rule = rule or sb.RULE
    bs = band_surface(A, band)
    if bs is None:
        return None
    xyz, valid, _, sl = bs
    rows = np.arange(A.valid.shape[0])[sl]
    found = _end_on(A, B, sl, rule, workers)
    if found is None:
        return None
    c_end, c1, dr, away, inward = found
    vc = _full_columns(valid)
    n = int(cols or max(3, (vc.max() - vc.min()) // 2))
    seq = c1 + away * np.arange(1, n + 1)             # B's columns beyond A's end, nearest first
    seq = seq[(seq >= 0) & (seq < B.valid.shape[1])]
    rb = rows + dr
    okr = (rb >= 0) & (rb < B.valid.shape[0])
    Bx = np.full((len(rows), len(seq), 3), np.nan)
    Bv = np.zeros((len(rows), len(seq)), bool)
    Bx[okr] = B.xyz[rb[okr]][:, seq]
    Bv[okr] = B.valid[rb[okr]][:, seq]
    Bx[~Bv] = 0.0
    a_cols = np.arange(vc.min(), vc.max() + 1)
    if inward == 1:                                    # A's first column is its end: B part comes before it
        J = np.concatenate([Bx[:, ::-1], xyz[:, a_cols]], 1)
        V = np.concatenate([Bv[:, ::-1], valid[:, a_cols]], 1)
        b_part = np.arange(len(seq))
        joint = (len(seq) - 1, len(seq))
    else:
        J = np.concatenate([xyz[:, a_cols], Bx], 1)
        V = np.concatenate([valid[:, a_cols], Bv], 1)
        b_part = np.arange(len(a_cols), len(a_cols) + len(seq))
        joint = (len(a_cols) - 1, len(a_cols))
    jl = np.linalg.norm(J[:, joint[0]] - J[:, joint[1]], axis=-1)[V[:, joint[0]] & V[:, joint[1]]]
    srow, scol = band_seed_rc(A, sl, band)
    scol = scol - int(a_cols[0]) + (len(seq) if inward == 1 else 0)
    return {"xyz": J, "valid": V, "seed_rc": (srow, scol), "b_cols": b_part, "b_name": B.name,
            "joint_edge_vox": [_r(float(np.median(jl)), 2), _r(float(jl.max()), 2)] if jl.size else None,
            "b_alone": (Bx, Bv), "a_alone": (xyz[:, a_cols], valid[:, a_cols], (srow, scol - (len(seq) if inward == 1
                                                                                             else 0)))}


def transverse_join(A, B, rule=None, band=None, workers=2):
    """A's band surface with the columns from the median plantable column on moved onto B along B's normal (where B
    is more than coincide_vox away; the vertices of those columns that cannot be moved become holes): one transverse
    switch line across the band. Returns a dict like seam_join."""
    np = _np()
    rule = rule or sb.RULE
    bs = band_surface(A, band)
    if bs is None:
        return None
    xyz, valid, _, sl = bs
    pos, okB, off = sb._project(xyz, valid, B, workers)
    apart = rule["references"]["coincide_vox"]
    plant = valid & okB & (np.abs(np.nan_to_num(off, nan=0.0)) > apart)
    if plant.sum() < 50:
        return None
    H, W = valid.shape
    cols = np.arange(W)[None, :].repeat(H, 0)
    mid = int(np.median(cols[plant]))
    mv = plant & (cols >= mid)
    x2 = np.where(mv[..., None], np.nan_to_num(pos), xyz)
    v2 = valid & ((cols < mid) | mv)
    srow, scol = band_seed_rc(A, sl, band)
    if scol >= mid:                                      # the seed stays on A's part
        a_part = valid & (cols < mid)
        rc = np.argwhere(a_part)
        k = np.argmin(np.abs(rc[:, 1] - mid / 2) + np.abs(rc[:, 0] - srow))
        srow, scol = int(rc[k, 0]), int(rc[k, 1])
    alone = np.where(mv[..., None], pos, np.nan)
    return {"xyz": x2, "valid": v2, "seed_rc": (srow, scol), "moved": mv, "b_name": B.name, "mid": mid,
            "moved_share": _r(mv.sum() / max(valid.sum(), 1)), "b_alone": (np.nan_to_num(alone), mv)}


def confetti(xyz, valid, n, shuffle=False):
    """The surface cut into n tiles of columns: every tile boundary column a hole, or (shuffle) the tiles in reverse
    order with no hole between, so neighboring columns are far apart (torn). Returns (xyz, valid, tiles)."""
    np = _np()
    vc = np.flatnonzero(valid.any(0))
    edges = np.linspace(vc.min(), vc.max() + 1, n + 1).round().astype(int)
    tiles = [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:]) if b - a >= 2]
    if not shuffle:
        v = valid.copy()
        for a, _ in tiles[1:]:
            v[:, a] = False
        return xyz.copy(), v, [(a + (1 if i else 0), b) for i, (a, b) in enumerate(tiles)]
    order = tiles[::-1]
    X = np.concatenate([xyz[:, a:b] for a, b in order], 1)
    V = np.concatenate([valid[:, a:b] for a, b in order], 1)
    out, c = [], 0
    for a, b in order:
        out.append((c, c + b - a))
        c += b - a
    return X, V, out


def fold(xyz, valid, nrm, c0, back, offset):
    """A fold with one transverse self-crossing line across every row: columns up to c0, then `back` columns back
    over the surface at +offset along the normal, then forward again at -offset, so the return passes through the
    surface between two columns, and back onto the sheet over three columns once past c0 (where nothing lies to
    cross). Only the fold is off the sheet, by at most `offset`."""
    np = _np()
    H, W = valid.shape
    n = np.nan_to_num(nrm)
    path = [(float(c), 0.0) for c in range(0, c0 + 1)]
    path += [(float(c0 - k), offset * min(1.0, k / 2.0)) for k in range(1, back + 1)]
    path += [(float(c), -offset * min(1.0, max(0.0, 1.0 - (c - c0 - 2) / 3.0)))
             for c in range(c0 - back + 1, W)]
    cols, vcols = [], []
    for x, y in path:
        i0 = int(math.floor(x))
        f = x - i0
        i1 = min(i0 + 1, W - 1)
        cols.append((1 - f) * xyz[:, i0] + f * xyz[:, i1] + y * ((1 - f) * n[:, i0] + f * n[:, i1]))
        vcols.append(valid[:, i0] & valid[:, i1] & np.isfinite(nrm[:, i0]).all(-1))
    return np.stack(cols, 1), np.stack(vcols, 1)


def plane(centre, normal, size, step, rng):
    """A flat grid of size (rows, cols) vertices `step` apart through `centre` with unit normal `normal`, turned by a
    random angle about it."""
    np = _np()
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    t = rng.uniform(0, 2 * math.pi)
    u, v = math.cos(t) * u + math.sin(t) * v, -math.sin(t) * u + math.cos(t) * v
    r = (np.arange(size[0]) - size[0] / 2) * step
    c = (np.arange(size[1]) - size[1] / 2) * step
    R, C = np.meshgrid(r, c, indexing="ij")
    xyz = np.asarray(centre, float)[None, None, :] + R[..., None] * v + C[..., None] * u
    return xyz, np.ones(size, bool), (size[0] // 2, size[1] // 2)


def random_normal(rng):
    np = _np()
    v = rng.normal(size=3)
    return v / np.linalg.norm(v)


def _g(res, name):
    return (res.get("windings", {}).get(name) or {}).get("G") or 0.0


def winding_controls(A, refs, man, rule=None, grule=None, counter=None, refs_dir=None, cache_dir=None, workers=2,
                     nogrid=None, rates=None):
    """Every planted control on one tune reference A in the band, each with a sham on which its criterion must
    fail. Returns the record (pass per control, the rates the gates are chosen from)."""
    np = _np()
    rule, grule = rule or sb.RULE, grule or GRULE
    C = grule["controls"]
    by = {r.name: r for r in refs}
    rec = {"winding": A.name}
    band = grule["band_z"]
    bs = band_surface(A, band)
    if bs is None:
        return {"winding": A.name, "skipped": "no labeled vertex in the band"}
    xyz, valid, nrm, sl = bs
    seed_rc = band_seed_rc(A, sl, band)
    rr = {A.name: reference_rates(A, refs, refs_dir, man, counter, rule, cache_dir, workers)} if rates is None else rates

    def sc(x, v, targets, seed_rc=None, best=False):
        res = score_grid(x, v, targets, refs, man, refs_dir, seed_rc=seed_rc, best=best, counter=counter, rule=rule,
                         grule=grule, cache_dir=cache_dir, workers=workers, ref_rates=rr)
        return res

    def ensure(name):
        if name not in rr:
            rr[name] = reference_rates(by[name], refs, refs_dir, man, counter, rule, cache_dir, workers)

    def brief(res, name):
        w = res["windings"][name]
        return {"G": w["G"], "credit": w["credit"], "net_cm2": w["net_cm2"], "wrong_cm2": w["wrong_cm2"],
                "seam_cm2": w["seam_cm2"], "switch_excess": w["gates"]["switch"]["excess"],
                "selfcross_excess": w["gates"]["selfcross"]["excess"], "gates_pass": w["gates"]["pass"]}

    # the band surface itself: G near 1, and the positive for both gates
    base = sc(xyz, valid, [A], seed_rc=seed_rc)
    g0 = _g(base, A.name)
    rec["band"] = {**brief(base, A.name), "band_cm2": base["windings"][A.name]["band_cm2"],
                   "reach": base["reach"], "pass": g0 >= 0.95,
                   "criterion": "the reference's own band surface gets G of at least 0.95"}
    # half a winding step along the normal, both ways: loses at least 80 % of its credit; a 1 voxel move must not
    pitch = next(x for x in man["references"] if x["name"] == A.name).get("local_pitch_vox") or 15.0
    orient = A.attrs.get("orient", 1)
    hs = {"pitch_vox": pitch, "moves": []}
    for sgn in (1, -1):
        off = sgn * orient * C["half_step_pitch"] * pitch
        x2, v2 = moved(xyz, valid, nrm, off)
        r2 = sc(x2, v2, [A], seed_rc=seed_rc)
        hs["moves"].append({"offset_vox": _r(off, 2), "G": _g(r2, A.name),
                            "kept": _r(_g(r2, A.name) / g0) if g0 else None})
    for sgn in (1, -1):
        off = sgn * C["tolerance_vox"]
        x2, v2 = moved(xyz, valid, nrm, off)
        r2 = sc(x2, v2, [A], seed_rc=seed_rc)
        hs.setdefault("tolerance", []).append({"offset_vox": off, "G": _g(r2, A.name),
                                               "kept": _r(_g(r2, A.name) / g0) if g0 else None})
    x2, v2 = moved(xyz, valid, nrm, orient * C["sham_move_vox"])
    sham = _g(sc(x2, v2, [A], seed_rc=seed_rc), A.name)
    hs["sham"] = {"offset_vox": orient * C["sham_move_vox"], "G": sham, "kept": _r(sham / g0) if g0 else None}
    hs["sham_fails"] = bool(g0 and sham / g0 > C["half_step_max_kept"])
    hs["pass"] = bool(g0 > 0 and all(m["kept"] is not None and m["kept"] <= C["half_step_max_kept"]
                                     for m in hs["moves"]) and hs["sham_fails"])
    hs["criterion"] = (f"moved half the local pitch either way it keeps at most {C['half_step_max_kept']} of its "
                       f"credit, and a {C['sham_move_vox']} voxel move (the sham) keeps more")
    rec["half_step"] = hs
    # seam join and transverse join with an adjacent tune winding
    rk = next(x for x in man["references"] if x["name"] == A.name)
    adj = [n for n in rk.get("chain_adjacent", []) if n in grule["split"]["tune"] and n in by]
    seam = None
    for nb in adj:
        sj = seam_join(A, by[nb], rule, band=band, workers=workers)
        if sj is not None:
            seam = sj
            break
    if seam is None:
        rec["seam"] = {"pass": None, "skipped": f"no end of {A.name} lies on a tune neighbor ({adj})"}
    else:
        B = by[seam["b_name"]]
        ensure(B.name)
        rj = sc(seam["xyz"], seam["valid"], [A, B], seed_rc=seam["seed_rc"])
        bx, bv = seam["b_alone"]
        rb = sc(bx, bv, [B], best=True)
        ax, av, arc = seam["a_alone"]
        ga0 = _g(sc(ax, av, [A], seed_rc=arc), A.name)
        ga, gb = _g(rj, A.name), _g(rj, B.name)
        gb0 = _g(rb, B.name)
        tol = C["seam_tolerance"]
        rec["seam"] = {"neighbour": B.name, "joint_edge_vox": seam["joint_edge_vox"], "G_own": ga, "G_own_alone": ga0,
                       "G_next": gb, "G_next_alone": gb0, **{k: v for k, v in brief(rj, A.name).items()
                                                            if k not in ("G",)},
                       "reach": rj["reach"]}
        rec["seam"]["pass"] = bool(abs(ga - ga0) <= tol and gb0 > 0.02 and abs(gb - gb0) <= tol
                                   and rj["windings"][A.name]["gates"]["pass"] is not False)
        rec["seam"]["criterion"] = (f"both windings keep their credit within {tol} (the next winding's part as "
                                    "scored alone), and the gates do not fail")
    tj = None
    for nb in adj:
        tj = transverse_join(A, by[nb], rule, band=band, workers=workers)
        if tj is not None:
            break
    if tj is None:
        rec["transverse"] = {"pass": None, "skipped": "no tune neighbor to plant on"}
    else:
        B = by[tj["b_name"]]
        ensure(B.name)
        rj = sc(tj["xyz"], tj["valid"], [A, B], seed_rc=tj["seed_rc"])
        bx, bv = tj["b_alone"]
        rb = sc(bx, bv, [B], best=True)
        gb, gb0 = _g(rj, B.name), _g(rb, B.name)
        rec["transverse"] = {"neighbour": B.name, "moved_share": tj["moved_share"], "G_own": _g(rj, A.name),
                             "G_next": gb, "G_next_alone": gb0,
                             **{k: v for k, v in brief(rj, A.name).items() if k not in ("G",)}, "reach": rj["reach"]}
        kept = gb / gb0 if gb0 else None
        rec["transverse"]["kept"] = _r(kept)
        rec["transverse"]["pass"] = bool(gb0 > 0.02 and kept is not None and kept <= C["transverse_max_kept"]
                                         and rj["windings"][A.name]["gates"]["pass"] is not True)
        rec["transverse"]["criterion"] = (f"the moved part keeps at most {C['transverse_max_kept']} of its credit for "
                                          "its own winding, and the gates do not pass")
        if seam is not None:
            # each join's criterion applied to the other must fail: the seam join keeps the next winding's credit
            rec["transverse"]["sham_fails"] = bool(rec["seam"]["G_next_alone"] and rec["seam"]["G_next"]
                                                   / rec["seam"]["G_next_alone"] > C["transverse_max_kept"])
            rec["seam"]["sham_fails"] = bool(abs(gb - gb0) > C["seam_tolerance"])
            rec["transverse"]["pass"] = rec["transverse"]["pass"] and rec["transverse"]["sham_fails"]
            rec["seam"]["pass"] = rec["seam"]["pass"] and rec["seam"]["sham_fails"]
    # confetti: cut into tiles (holes between them), and the tiles reversed (torn edges between them)
    cf = {"tiles": C["confetti_tiles"], "arms": []}
    for shuffle in (False, True):
        cx, cv, tiles = confetti(xyz, valid, C["confetti_tiles"], shuffle)
        r2 = sc(cx, cv, [A], best=True)
        alone = [_g(sc(cx[:, a:b], cv[:, a:b], [A], best=True), A.name) for a, b in tiles]
        cf["arms"].append({"shuffled": shuffle, "G": _g(r2, A.name), "largest_tile": max(alone), "tiles_G": alone,
                           "components": r2["reach"]["components"], "torn_edges": r2["reach"]["torn_edges"]})
    big = max(a["largest_tile"] for a in cf["arms"])
    cf["sham_fails"] = bool(g0 > big + C["confetti_tolerance"])     # the uncut surface is credited more than a tile
    cf["pass"] = bool(all(abs(a["G"] - a["largest_tile"]) <= C["confetti_tolerance"] for a in cf["arms"])
                      and cf["sham_fails"])
    cf["criterion"] = (f"credited its largest tile within {C['confetti_tolerance']}, while the uncut surface is "
                       "credited more (the sham)")
    rec["confetti"] = cf
    # a fold: one transverse self-crossing line across the band; G barely moves, the self-crossing gate must see it
    W = valid.shape[1]
    fx, fv = fold(xyz, valid, nrm, W // 2, C["fold_back_cols"], C["fold_offset_vox"])
    rf = sc(fx, fv, [A], seed_rc=seed_rc)
    rec["fold"] = {**brief(rf, A.name), "selfcross": rf["rates"]["selfcross"],
                   "band_selfcross": base["rates"]["selfcross"],
                   "pass": None, "criterion": "a negative for the self-crossing gate (decided by choose_gates)"}
    # no-grid stand-ins, on the windings the rule names
    if A.name in C["nogrid_windings"]:
        rec["nogrid"] = nogrid_controls(A, xyz, valid, nrm, sl, seed_rc, sc, grule, nogrid)
    # version 2: the same fold and transverse join planted in the band rows of the whole mesh, and the whole mesh itself
    if _windowed(grule) and A.name in C.get("whole_mesh_windings", []):
        rec["whole"] = whole_mesh_controls(A, sl, seed_rc, tj, by, sc, ensure, brief, grule)
    # what choose_gates reads: each gate's excess on the positives and on its negatives (None when unmeasured, which
    # makes the controls run invalid)
    rec["positives"] = {"band": {"switch": rec["band"]["switch_excess"], "selfcross": rec["band"]["selfcross_excess"]}}
    if seam is not None:
        rec["positives"]["seam"] = {"switch": rec["seam"]["switch_excess"], "selfcross": rec["seam"]["selfcross_excess"]}
    rec["negatives"] = {"fold": {"selfcross": rec["fold"]["selfcross_excess"]}}
    if tj is not None:
        rec["negatives"]["transverse"] = {"switch": rec["transverse"]["switch_excess"]}
    if "whole" in rec:
        wm = rec["whole"]
        rec["positives"]["whole"] = {"switch": wm["mesh"]["switch_excess"], "selfcross": wm["mesh"]["selfcross_excess"]}
        rec["negatives"]["whole_fold"] = {"selfcross": wm["fold"]["selfcross_excess"]}
        if "switch_excess" in wm["transverse"]:
            rec["negatives"]["whole_transverse"] = {"switch": wm["transverse"]["switch_excess"]}
    return rec


def whole_mesh_controls(A, sl, seed_rc, tj, by, sc, ensure, brief, grule):
    """Version 2's whole-mesh controls on one tune reference: its whole mesh (a positive of both gates), and the band
    controls' fold and transverse join planted in the band rows of the whole mesh (negatives). The fold's extra
    columns are holes outside the band rows, and the transverse join's moved block is cut off from the rows above and
    below it by a hole row, so each defect is the band control's own, in a surface several times larger."""
    np = _np()
    C = grule["controls"]
    xyz, valid, nrm = A.xyz, A.valid, A.normals
    H, W = valid.shape
    seed = (seed_rc[0] + sl.start, seed_rc[1])

    def rec_of(res, extra=None):
        r = {**brief(res, A.name), "area_cm2": res.get("area_cm2"),
             "whole_surface_excess": res["windings"][A.name].get("whole_surface_excess"),
             "selfcross": res["rates"]["selfcross"], "switch_crossings": res["rates"]["switch_crossings"]}
        r.update(extra or {})
        return r

    out = {"criterion": "the whole mesh passes both gates; the fold planted in its band rows fails the self-crossing "
                        "gate and the transverse join the switch gate (decided by gate_checks)", "pass": None}
    out["mesh"] = rec_of(sc(xyz, valid, [A], seed_rc=seed))
    # the fold, in the band rows: the band rows run along its path; the other rows keep their columns, with the
    # 2 * back columns the path adds as holes
    c0, back = W // 2, C["fold_back_cols"]
    fx, fv = fold(xyz[sl], valid[sl], nrm[sl], c0, back, C["fold_offset_vox"])
    X = np.zeros((H, W + 2 * back, 3))
    V = np.zeros((H, W + 2 * back), bool)
    keep = np.r_[0:c0 + 1, c0 + 2 * back + 1:W + 2 * back]
    X[:, keep] = np.nan_to_num(xyz)
    V[:, keep] = valid
    X[sl], V[sl] = np.nan_to_num(fx), fv
    fseed = (seed[0], seed[1] + (2 * back if seed[1] > c0 else 0))
    out["fold"] = rec_of(sc(X, V, [A], seed_rc=fseed))
    # the transverse join, in the band rows, its moved block cut off above and below by a hole row
    if tj is None:
        out["transverse"] = {"skipped": "no tune neighbor to plant on"}
        return out
    B = by[tj["b_name"]]
    ensure(B.name)
    X, V = xyz.copy(), valid.copy()
    X[sl], V[sl] = tj["xyz"], tj["valid"]
    for r in (sl.start - 1, sl.stop):
        if 0 <= r < H:
            V[r, tj["mid"]:] = False
    res = sc(X, V, [A, B], seed_rc=(tj["seed_rc"][0] + sl.start, tj["seed_rc"][1]))
    out["transverse"] = rec_of(res, {"neighbour": B.name})
    return out


def nogrid_controls(A, xyz, valid, nrm, sl, seed_rc, sc, grule, nogrid=None):
    """No-grid stand-ins on one tune winding: the real no-grid trace (if given) moved so its seed sits on the band
    seed vertex, and planes of its size through that vertex at random orientations. Each must get G at most
    nogrid_max; the sham, a patch of the band surface of the same size around the seed (a surface that follows the
    winding), must get more."""
    np = _np()
    C = grule["controls"]
    rng = np.random.default_rng([C["seed"], int(A.name[1:])])
    centre = xyz[seed_rc]
    arms = []
    if nogrid is not None:
        nx, nv, nseed = nogrid
        shift = centre - np.asarray(nseed, float)
        res = sc(nx + shift, nv, [A], seed_rc=_nearest_rc(nx + shift, nv, centre))
        arms.append({"stand_in": "the given no-grid trace moved so its seed lies on the band seed vertex",
                     "G": _g(res, A.name)})
    step = 20.0
    for i in range(C["nogrid_planes"]):
        px, pv, prc = plane(centre, random_normal(rng), C["nogrid_size"], step, rng)
        res = sc(px, pv, [A], seed_rc=prc)
        arms.append({"stand_in": f"plane {i} of {C['nogrid_size'][0]} by {C['nogrid_size'][1]} vertices, random "
                                 "orientation", "G": _g(res, A.name)})
    # tangent plane: the most a flat sheet through the seed can get (reported, not a gate)
    px, pv, prc = plane(centre, nrm[seed_rc], C["nogrid_size"], step, rng)
    tangent = _g(sc(px, pv, [A], seed_rc=prc), A.name)
    h, w = C["nogrid_size"]
    r0 = max(0, seed_rc[0] - h // 2)
    c0 = max(0, seed_rc[1] - w // 2)
    sx, sv = xyz[r0:r0 + h, c0:c0 + w], valid[r0:r0 + h, c0:c0 + w]
    sham = _g(sc(sx, sv, [A], seed_rc=(seed_rc[0] - r0, seed_rc[1] - c0)), A.name)
    out = {"arms": arms, "tangent_plane_G": tangent, "sham": {"stand_in": "the band surface around the seed, same "
                                                              "size", "G": sham},
           "sham_fails": bool(sham > C["nogrid_max"])}
    out["pass"] = bool(all(a["G"] <= C["nogrid_max"] for a in arms) and out["sham_fails"])
    out["criterion"] = f"every stand-in gets G of at most {C['nogrid_max']}, the sham more"
    return out


def _nearest_rc(xyz, valid, p):
    np = _np()
    d = np.linalg.norm(np.where(valid[..., None], xyz, np.inf) - np.asarray(p)[None, None, :], axis=-1)
    r, c = np.unravel_index(int(np.argmin(d)), d.shape)
    return int(r), int(c)


def choose_gates(records, grule=None):
    """The gate thresholds the controls allow: for each gate, lo the highest excess of a positive (band surfaces and
    seam joins), hi the lowest of its negatives (transverse joins for the switch gate, folds for the self-crossing
    gate); the threshold is their midpoint floored to `step`, and must clear both by `margin`, else there is none
    and the reason says why."""
    grule = grule or GRULE
    out = {}
    for k, gd in grule["gates"].items():
        pos = [v[k] for r in records for v in r.get("positives", {}).values() if v.get(k) is not None]
        neg = [v[k] for r in records for v in r.get("negatives", {}).values() if v.get(k) is not None]
        unm = sum(1 for r in records for d in ("positives", "negatives") for v in r.get(d, {}).values()
                  if k in v and v[k] is None)
        rec = {"positives": len(pos), "negatives": len(neg), "lo": _r(max(pos)) if pos else None,
               "hi": _r(min(neg)) if neg else None, "threshold": None}
        if unm:
            rec["unmeasured"] = unm
        if not pos or not neg:
            rec["reason"] = "no positive or no negative control measured"
            out[k] = rec
            continue
        lo, hi = max(pos), min(neg)
        step = gd["step"]
        t = math.floor(round((lo + hi) / 2 / step, 9)) * step
        if t < lo + gd["margin"] - 1e-9 or t > hi - gd["margin"] + 1e-9:
            rec["reason"] = (f"positives reach {lo:.4g} and negatives {hi:.4g}: no threshold clears both by "
                             f"{gd['margin']}")
            out[k] = rec
            continue
        rec["threshold"] = _r(t, 6)
        rec["rule_threshold"] = gd["threshold"]
        rec["rule_matches"] = gd["threshold"] is not None and abs(gd["threshold"] - t) < 1e-9
        out[k] = rec
    return out


def gate_checks(records, grule=None):
    """Under the rule's frozen thresholds: every positive control passes its gate and every negative fails it. A
    control whose excess could not be measured is listed as unmeasured and fails the check, never dropped."""
    grule = grule or GRULE
    out = {}
    for k, gd in grule["gates"].items():
        t = gd["threshold"]
        if t is None:
            out[k] = None
            continue
        pos = [(r["winding"], c, v[k]) for r in records for c, v in r.get("positives", {}).items() if k in v]
        neg = [(r["winding"], c, v[k]) for r in records for c, v in r.get("negatives", {}).items() if k in v]
        unm = [[w, c] for w, c, x in pos + neg if x is None]
        pos = [p for p in pos if p[2] is not None]
        neg = [n for n in neg if n[2] is not None]
        out[k] = {"threshold": t, "positives": len(pos), "positives_passed": sum(1 for *_, x in pos if x <= t),
                  "negatives": len(neg), "negatives_caught": sum(1 for *_, x in neg if x > t),
                  "unmeasured": unm,
                  "misses": [[w, c, x] for w, c, x in pos if x > t] + [[w, c, x] for w, c, x in neg if x <= t]}
        out[k]["pass"] = bool(pos and neg and not out[k]["misses"] and not unm)
    return out


def planted(records, grule=None):
    """How many positives and negatives of each gate the records planted, counted from the controls themselves (band
    surfaces and seam joins, transverse joins and folds, and the whole-mesh controls), measured or not."""
    grule = grule or GRULE
    n = {"band": 0, "seam": 0, "transverse": 0, "fold": 0, "whole": 0, "whole_fold": 0, "whole_transverse": 0}
    for r in records:
        for k in ("band", "seam", "transverse", "fold"):
            if isinstance(r.get(k), dict) and not r[k].get("skipped"):
                n[k] += 1
        w = r.get("whole")
        if isinstance(w, dict):
            n["whole"] += 1 if isinstance(w.get("mesh"), dict) else 0
            n["whole_fold"] += 1 if isinstance(w.get("fold"), dict) else 0
            n["whole_transverse"] += 1 if isinstance(w.get("transverse"), dict) and not w["transverse"].get(
                "skipped") else 0
    pos = n["band"] + n["seam"] + n["whole"]
    out = {"switch": {"positives": pos, "negatives": n["transverse"] + n["whole_transverse"]},
           "selfcross": {"positives": pos, "negatives": n["fold"] + n["whole_fold"]}, "controls": n}
    return {k: v for k, v in out.items() if k in grule["gates"] or k == "controls"}


def run_controls(refs_dir=sb.DEFAULT_REFS, names=None, counter="vc3d", rule=None, grule=None, cache_dir=None,
                 workers=2, nogrid=None, log=None):
    """The planted controls on the tune windings (or `names`, which must be tune windings), the gate thresholds they
    give and whether every control passed."""
    np = _np()
    rule, grule = rule or sb.RULE, grule or GRULE
    t0 = time.time()
    names = list(names or grule["split"]["tune"])
    bad = [n for n in names if n not in grule["split"]["tune"]]
    if bad:
        raise GError(f"controls run on tune windings only, not {bad}")
    man, refs = sb.load_refs(refs_dir, rule)
    by = {r.name: r for r in refs}
    if counter == "vc3d":
        counter = vc3d_counter(threads=workers)
    ng = None
    if nogrid is not None:
        nx, nv, _ = sb.read_tifxyz(nogrid)
        s = _read_seed(nogrid)
        if s is None:
            raise GError(f"{nogrid}: no seed in its meta.json")
        ng = (nx, nv, s)
    recs = []
    for n in names:
        if n not in by:
            recs.append({"winding": n, "skipped": "no reference"})
            continue
        r = winding_controls(by[n], refs, man, rule, grule, counter, refs_dir, cache_dir, workers, ng)
        recs.append(r)
        sb._say(log, f"gscore: controls at {n}: " + ", ".join(f"{k} {r.get(k, {}).get('pass')}" for k in CONTROL_KEYS
                                                            if k in r) + f" ({time.time() - t0:.0f} s)")
    gates = choose_gates(recs, grule)
    checks = gate_checks(recs, grule)
    plant = planted(recs, grule)
    dropped = []
    for k, c in checks.items():
        # every planted positive and negative must reach the gate check, measured
        if c is None:
            continue
        c["planted"] = {"positives": plant[k]["positives"], "negatives": plant[k]["negatives"]}
        if (c["positives"], c["negatives"]) != (plant[k]["positives"], plant[k]["negatives"]):
            c["pass"] = False
            dropped.append(f"{k}: {c['positives']} of {plant[k]['positives']} positives and {c['negatives']} of "
                           f"{plant[k]['negatives']} negatives measured")
    summary = {}
    for k in CONTROL_KEYS:
        vals = [r[k]["pass"] for r in recs if isinstance(r.get(k), dict) and r[k].get("pass") is not None]
        summary[k] = {"pass": sum(1 for v in vals if v), "of": len(vals)}
    failed = [k for k, v in summary.items() if v["of"] and v["pass"] < v["of"]]
    out = {"kind": "kit-surfbench-gscore-controls", "gscore_rule_digest": grule_digest(grule),
           "run_rule_digest": sb.digest(run_rule(man, grule)), "surfbench_rule_digest": sb.rule_digest(rule),
           "manifest_digest": man["digest"], "windings": names, "nogrid_trace": str(nogrid) if nogrid else None,
           "gscore_rule_version": grule.get("version"),
           "selfcross_counted": counter is not None, "records": recs, "summary": summary, "gates": gates,
           "gate_checks": checks, "planted": plant["controls"], "unmeasured": dropped, "failed": failed,
           # valid: every control passed, the controls give a threshold for each gate, the rule holds exactly
           # those thresholds, and under them every positive passes and every negative fails its gate
           "valid": bool(recs) and not failed and counter is not None and not dropped
           and all(g["threshold"] is not None and g.get("rule_matches") for g in gates.values())
           and all(c is not None and c["pass"] for c in checks.values()),
           "seconds": round(time.time() - t0, 1)}
    _ = np
    return out
