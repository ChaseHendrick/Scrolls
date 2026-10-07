"""Certified elimination of candidate title strings against a measured region.

Method inspiration: the ball-arithmetic computer-assisted proofs of
C. Hendrick (Zenodo 10.5281/zenodo.23096253, 23096228, 23096191). Here every
quantity is a closed interval [lo, hi] of exact rationals (fractions.Fraction),
so no rounding occurs and every elimination is a proved inequality, not a
floating-point comparison. A ball (center c, radius r) is the interval
[c - r, c + r].

A candidate is ELIMINATED only when one of its predicted intervals is disjoint
from the measured interval for the same quantity; the certificate is the
inequality pred.hi < meas.lo or pred.lo > meas.hi. Surviving is not evidence
of a match and never a reading: it only means the geometry cannot rule it out.
"""
import json
from fractions import Fraction as F


def q(x):
    """Exact rational from int, str or float (floats via their decimal repr)."""
    if isinstance(x, F):
        return x
    if isinstance(x, float):
        return F(repr(x))
    return F(x)


class Iv:
    __slots__ = ("lo", "hi")

    def __init__(self, lo, hi=None):
        lo = q(lo)
        hi = lo if hi is None else q(hi)
        if lo > hi:
            raise ValueError("empty interval [%s, %s]" % (lo, hi))
        self.lo, self.hi = lo, hi

    @classmethod
    def ball(cls, center, radius):
        c, r = q(center), q(radius)
        if r < 0:
            raise ValueError("negative radius")
        return cls(c - r, c + r)

    @classmethod
    def of(cls, v):
        if isinstance(v, Iv):
            return v
        if isinstance(v, dict):
            return cls.ball(v["center"], v["radius"])
        if isinstance(v, (list, tuple)):
            return cls(v[0], v[1])
        return cls(v)

    def __add__(self, o):
        o = Iv.of(o)
        return Iv(self.lo + o.lo, self.hi + o.hi)

    __radd__ = __add__

    def __sub__(self, o):
        o = Iv.of(o)
        return Iv(self.lo - o.hi, self.hi - o.lo)

    def __mul__(self, o):
        o = Iv.of(o)
        p = [self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi]
        return Iv(min(p), max(p))

    __rmul__ = __mul__

    def hull(self, o):
        return Iv(min(self.lo, o.lo), max(self.hi, o.hi))

    @property
    def center(self):
        return (self.lo + self.hi) / 2

    @property
    def radius(self):
        return (self.hi - self.lo) / 2

    def disjoint(self, o):
        """Return a certifying inequality string if disjoint, else None."""
        if self.hi < o.lo:
            return "pred.hi %s < meas.lo %s" % (self.hi, o.lo)
        if self.lo > o.hi:
            return "pred.lo %s > meas.hi %s" % (self.lo, o.hi)
        return None

    def as_dict(self):
        return {"lo": str(self.lo), "hi": str(self.hi),
                "center": float(self.center), "radius": float(self.radius)}


def letters(line):
    return sum(1 for ch in line if not ch.isspace())


def predict(lines, priors):
    """Predicted intervals for one candidate (list of lines)."""
    W = Iv.of(priors["letter_width_mm"])
    S = Iv.of(priors["letter_spacing_mm"])
    G = Iv.of(priors.get("word_gap_mm", [0, 0]))
    H = Iv.of(priors["letter_height_mm"])
    widths = []
    for line in lines:
        n = letters(line)
        gaps = max(n - 1, 0)
        words = len(line.split())
        w = W * n + S * gaps + G * max(words - 1, 0)
        widths.append(w)
    longest = widths[0]
    for w in widths[1:]:
        longest = Iv(max(longest.lo, w.lo), max(longest.hi, w.hi))
    counts = [letters(l) for l in lines]
    return {
        "width_mm": longest,
        "lines": Iv(len(lines)),
        "letters": Iv(sum(counts)),
        "letter_height_mm": H,
    }


def measure(region):
    """Measured intervals with propagated uncertainty.

    width_mm = width_px * pixel_mm * (1 + distortion) + threshold_px * pixel_mm,
    where pixel_mm, distortion and threshold_px are intervals (balls).
    letters and lines are integer intervals counted under the threshold range.
    """
    px = Iv.of(region["pixel_mm"])
    dist = Iv(1) + Iv.of(region.get("distortion", 0))
    thr = Iv.of(region.get("threshold_px", 0))
    out = {}
    if "width_px" in region:
        out["width_mm"] = Iv.of(region["width_px"]) * px * dist + thr * px
    if "letter_height_px" in region:
        out["letter_height_mm"] = Iv.of(region["letter_height_px"]) * px * dist + thr * px
    for k in ("lines", "letters"):
        if k in region:
            out[k] = Iv.of(region[k])
    return out


def check(priors, region):
    meas = measure(region)
    survivors, eliminated = [], []
    for cand in priors["candidates"]:
        pred = predict(cand["lines"], priors)
        certs = []
        for k, m in meas.items():
            c = pred[k].disjoint(m)
            if c:
                certs.append({"quantity": k, "inequality": c})
        rec = {"id": cand["id"],
               "predicted": {k: v.as_dict() for k, v in pred.items()}}
        if certs:
            rec["certificates"] = certs
            eliminated.append(rec)
        else:
            survivors.append(rec)
    return {
        "region": region.get("id", "region"),
        "measured": {k: v.as_dict() for k, v in meas.items()},
        "survivors": survivors,
        "eliminated": eliminated,
        "note": "Survivors are not readings: geometry only fails to exclude them. Model output; papyrologist review required.",
    }


def cmd_titlecheck(args):
    with open(args.priors) as f:
        priors = json.load(f)
    with open(args.region) as f:
        regions = json.load(f)
    if isinstance(regions, dict):
        regions = [regions]
    res = [check(priors, r) for r in regions]
    print(json.dumps(res, indent=1))
    return 0
