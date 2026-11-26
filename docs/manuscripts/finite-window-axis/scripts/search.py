"""Adversarial search for the d-dimensional axis (line field) extension.

Admissible discrete class (a subset of the continuous admissible class):
  t in [-L/2, L/2], n(0) = e1. Each side has N cells with free durations
  (summing to L/2). In each cell n(t) moves at constant speed along a great
  circle arc of angle ell_k <= Omega * dur_k, in a free tangent direction.
  The weight is constant w_k in [1, R] on each cell.
Cell integrals of n n^T over a great circle arc are in closed form, so M is
exact (no sampling) for the real line field case.
"""
import numpy as np
from scipy.optimize import minimize
import sys, json

def delta(b, R):
    s = np.sqrt(R)
    return np.arctan2(s*np.sin(b/2), 1 + s*np.cos(b/2))

def sig(x):
    return 1/(1+np.exp(-x))

def arc_nnT(p, c, ell, dur):
    """int over a cell of duration dur of n n^T, n(s)=cos s p + sin s c, s in [0,ell] uniform in time."""
    if ell < 1e-12:
        return dur*np.outer(p, p)
    Icc = ell/2 + np.sin(2*ell)/4
    Iss = ell/2 - np.sin(2*ell)/4
    Ics = np.sin(ell)**2/2
    A = Icc*np.outer(p, p) + Iss*np.outer(c, c) + Ics*(np.outer(p, c)+np.outer(c, p))
    return (dur/ell)*A

def build(params, d, N, Om, L, R):
    """Return list of (p, c, ell, dur, w) for all cells, both sides."""
    k = d + 3  # per cell: d raw direction, 1 arc frac, 1 weight, 1 duration logit
    P = params.reshape(2, N, k)
    cells = []
    for side in range(2):
        p = np.zeros(d); p[0] = 1.0
        logits = P[side, :, d+2]
        durs = np.exp(logits - logits.max()); durs = durs/durs.sum()*(L/2)
        for j in range(N):
            r = P[side, j, :d]
            c = r - (r@p)*p
            nc = np.linalg.norm(c)
            if nc < 1e-12:
                c = np.zeros(d); c[1 if abs(p[1]) < 0.9 else 2 % d] = 1; c = c-(c@p)*p; nc = np.linalg.norm(c)
            c = c/nc
            ell = Om*durs[j]*sig(P[side, j, d])
            w = 1 + (R-1)*sig(P[side, j, d+1])
            cells.append((p.copy(), c, ell, durs[j], w))
            p = np.cos(ell)*p + np.sin(ell)*c
            p = p/np.linalg.norm(p)
    return cells

def M_of(cells, d):
    M = np.zeros((d, d)); W = 0
    for (p, c, ell, dur, w) in cells:
        M += w*arc_nnT(p, c, ell, dur); W += w*dur
    return M/W

def err_line(M):
    ev, V = np.linalg.eigh(M)
    v = V[:, -1]
    return np.arccos(min(1.0, abs(v[0]))), ev

def objective(params, d, N, Om, L, R):
    M = M_of(build(params, d, N, Om, L, R), d)
    e, _ = err_line(M)
    return -e

def seed_2d(d, N, R, b, beta):
    """Seed near the 2D extremal: V path theta = Om|t|, weight R where 2 Om|t|>beta."""
    k = d+3
    P = np.zeros((2, N, k))
    P[:, :, 1] = 1.0  # direction e2 on both sides (n tilts the same way: theta = Om|t|)
    P[:, :, d] = 8.0  # full speed
    # durations equal; weight R on cells beyond threshold
    tcells = (np.arange(N)+0.5)/N  # fraction of half length
    for j in range(N):
        P[:, j, d+1] = 8.0 if tcells[j]*b > beta else -8.0
    return P.ravel()

def run(d, b, R, restarts, N, rng, extra_seeds=True):
    L = 1.0; Om = b/L
    dl = delta(b, R); beta = 2*dl
    best = 0; bestp = None
    seeds = []
    if extra_seeds:
        seeds.append(seed_2d(d, N, R, b, beta))
    for i in range(restarts):
        seeds.append(rng.normal(size=2*N*(d+3))*rng.choice([0.5, 1.5, 3.0]))
    best_rand = 0
    for i, s in enumerate(seeds):
        res = minimize(objective, s, args=(d, N, Om, L, R), method='L-BFGS-B',
                       options={'maxiter': 400, 'maxfun': 200000})
        e = -res.fun
        if i >= (1 if extra_seeds else 0):
            best_rand = max(best_rand, e)
        if e > best:
            best = e; bestp = res.x
    # nonplanarity of best: smallest singular values of point cloud
    cells = build(bestp, d, N, Om, L, R)
    pts = np.array([c[0] for c in cells])
    sv = np.linalg.svd(pts, compute_uv=False)
    return dict(d=d, b=b, R=R, delta=dl, best=best, ratio=best/dl, ratio_random_only=best_rand/dl,
                nonplanarity=float(sv[-1]/sv[0]) if d > 2 else 0.0)

if __name__ == '__main__':
    d = int(sys.argv[1]); restarts = int(sys.argv[2]); N = int(sys.argv[3])
    rng = np.random.default_rng(int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    cases = [(0.3, 1), (0.3, 10), (0.8, 2), (0.8, 30), (1.2, 4), (np.pi/2, 1), (np.pi/2, 9), (np.pi/2, 100)]
    if len(sys.argv) > 5:
        cases = json.loads(sys.argv[5])
    for b, R in cases:
        r = run(d, b, R, restarts, N, rng)
        print(json.dumps({k: (round(v, 7) if isinstance(v, float) else v) for k, v in r.items()}), flush=True)
