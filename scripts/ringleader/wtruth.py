"""Seam-free winding truth for scoring Ringleader labels against published hand-traced windings.

A winding's rank changes where its tracer happened to start and end the turn, while slicelab's label (the turn
number k of the unwrapped angle Phi = theta' + 2 pi k) changes at slicelab's own start ray. So label minus rank is
not constant even for a perfect labeling. Here each reference vertex gets its unwrapped angle about the axis
(rlcommon.turn_angles, continuous along the mesh), brought to one common branch for all windings, and a point
matched to it gets

    turn = rank + (alpha' - theta') / 360     (an integer, since alpha' and theta' agree mod 360)

the number of the turn it lies on in slicelab's own convention. label minus turn is then constant for a perfect
labeling, wherever the references start. Seam overlaps (a winding traced past a full turn) are masked.

The hand (which way theta' runs) comes from the references themselves (Truth.hand), never from a labeling:
score.py converts the labels' theta' to it.

The rank of a winding is its number (w023 is 23), so windings left out of the reference set stay gaps. Next to a
winding number that is not loaded, a real sheet may still lie there: a matched point offset more than
near_missing_vox toward that side is left unknown.
"""

import math
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent))
import rlcommon  # noqa: E402

NEAR_MISSING_VOX = 2.0
MATCH_VOX = 4.0             # a point lies on a winding when its nearest footprint match is within this many voxels


def rank_from_name(name):
    """The winding's number from its name (w023 -> 23), so gaps stay gaps."""
    m = re.match(r"w(\d+)", name)
    if not m:
        raise ValueError(f"{name}: not a winding name like w023")
    return int(m.group(1))


def missing_sides(names):
    """{name: [sides]} where the next winding number outward (+1) or inward (-1) is not among the names."""
    have = {rank_from_name(n) for n in names}
    out = {}
    for n in names:
        k = rank_from_name(n)
        sides = [s for s in (1, -1) if k + s not in have]
        if sides:
            out[n] = sides
    return out


class Truth:
    def __init__(self, refs, axis, near_missing_vox=NEAR_MISSING_VOX, d=MATCH_VOX):
        self.refs = refs
        self.d = float(d)
        for r in refs:
            r.attrs["rank"] = rank_from_name(r.name)
        self.missing_side = missing_sides([r.name for r in refs])
        self.near_missing_vox = float(near_missing_vox)
        self.axis_zyx = np.stack([axis.pts[:, 2], axis.pts[:, 1], axis.pts[:, 0]], -1)
        self._axis = axis
        self.seam, seam_info = rlcommon.seam_masks(refs, self.axis_zyx)
        # the hand from the references alone: where a mesh covers a sector twice, the outer copy is the traced
        # end on the next turn out. Outer = later (radius grows with the traced angle) means theta' = +theta
        # (hand +1); outer = earlier means the spiral runs inward as theta grows (hand -1).
        outer = [v.get("outer") for v in seam_info.values() if v.get("outer")]
        self.hand_votes = {"later": outer.count("later"), "earlier": outer.count("earlier")}
        self.hand = -1 if self.hand_votes["earlier"] > self.hand_votes["later"] else 1
        self.normal_out = {r.gid: self._normal_sign(r) for r in refs if r.name in self.missing_side}
        self.alpha = {}
        meds = []
        for r in refs:
            a = rlcommon.turn_angles(r.xyz, r.valid, self.axis_zyx)
            self.alpha[r.gid] = a
            meds.append(float(np.nanmedian(a)))
        # one common branch: each mesh's angles moved by whole turns so its median lies near the circular mean
        c = np.radians(np.asarray(meds))
        A0 = math.degrees(math.atan2(np.sin(c).mean(), np.cos(c).mean()))
        self.A0 = A0
        for r, m in zip(refs, meds):
            self.alpha[r.gid] = self.alpha[r.gid] - 360.0 * round((m - A0) / 360.0)

    def _radius(self, P):
        """Distance from the axis in the slice plane, per point (x, y, z)."""
        c = np.array([self._axis.at(float(z)) for z in P[:, 2]], float)
        return np.hypot(P[:, 0] - c[:, 0], P[:, 1] - c[:, 1])

    def _normal_sign(self, r, n=4000, off=4.0, seed=0):
        """+1 when the reference's normal points away from the axis (outward), -1 when inward: points moved
        off its own vertices by +off along the normal are matched back, and the sign of the radius change
        decides (majority)."""
        pts, nrm, _, _ = r.scoring()
        if not len(pts):
            return 1
        rng = np.random.default_rng(seed)
        i = rng.choice(len(pts), min(n, len(pts)), replace=False)
        P0, P1 = pts[i], pts[i] + off * nrm[i]
        dr = self._radius(P1) - self._radius(P0)
        return 1 if (dr > 0).mean() >= 0.5 else -1

    def label(self, P, workers=4, amb=False, contact_d=8.0):
        """Per point (x, y, z): rank (or -1), alpha' of the matched vertex in degrees (NaN when unmatched). With
        amb, also whether two references (neither masked) lie within d of the point: such a point sits where two
        windings are pressed closer than the matching distance, so its rank is a coin toss between them; and
        whether two lie within contact_d (the contact stratum: another winding within 8 voxels)."""
        refs = self.refs
        d = self.d
        S, IN, J = rlcommon.matches(P, refs, workers)
        lab, best = rlcommon.nearest_on(S, IN, J, refs, d)
        rank = {r.gid: r.attrs.get("rank") for r in refs}
        out = np.full(len(P), -1, np.int64)
        alpha = np.full(len(P), np.nan)
        for i, g in enumerate(lab):
            if g >= 0 and isinstance(rank.get(int(g)), int):
                r = refs[int(best[i])]
                j = int(J[int(best[i]), i])
                if self.seam.get(r.gid) is not None and self.seam[r.gid].ravel()[j]:
                    continue
                s_i = S[int(best[i]), i]
                if any(side * self.normal_out[r.gid] * s_i > self.near_missing_vox
                       for side in self.missing_side.get(r.name, ())):
                    continue                    # offset toward a winding not loaded: may lie on its sheet
                out[i] = rank[int(g)]
                alpha[i] = self.alpha[r.gid].ravel()[j]
        if not amb:
            return out, alpha
        near = np.zeros(len(P), np.int64)
        nearc = np.zeros(len(P), np.int64)
        for k, r in enumerate(refs):
            ad = np.abs(np.nan_to_num(S[k], nan=np.inf))
            ok = IN[k].copy()
            m_ = self.seam.get(r.gid)
            if m_ is not None:
                ok &= ~m_.ravel()[J[k]]
            near += ok & (ad <= d)
            nearc += ok & (ad <= contact_d)
        return out, alpha, (near >= 2) & (out >= 0), (nearc >= 2) & (out >= 0)


def turns(rank, alpha, theta_p, hand):
    """Turn number in slicelab's convention (NaN where unmatched), and the distance of the unrounded value from an
    integer (a check of the truth: it should stay small)."""
    a = hand * alpha
    t = rank + (a - np.degrees(theta_p)) / 360.0
    out = np.where(rank >= 0, np.rint(t), np.nan)
    resid = np.where(rank >= 0, np.abs(t - np.rint(t)), np.nan)
    return out, resid
