"""Adversarial search for Corollary B (SO(3), chordal mean).

The rotation path is piecewise geodesic in SO(3): on each cell the unit
quaternion moves along a great circle at constant speed, quaternion arc
<= (Omega/2)*dur (rotation-angle speed <= Omega). B = int w R(t) dt is computed
with 12-point Gauss-Legendre per cell on the rotation matrices themselves
(not through the quaternion matrix), the estimate is the SVD projection of B
onto SO(3), and the error is the rotation angle of Rhat^T R(0).
"""
import numpy as np, sys, json
from scipy.optimize import minimize
from search import build, delta

def quat2rot(q):
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

gx, gw = np.polynomial.legendre.leggauss(12)

def B_of(cells):
    B = np.zeros((3, 3)); W = 0
    for (p, c, ell, dur, w) in cells:
        for x, a in zip(gx, gw):
            s = ell*(x+1)/2
            q = np.cos(s)*p + np.sin(s)*c
            B += w*a*dur/2*quat2rot(q)
        W += w*dur
    return B/W

def proj_SO3(B):
    U, S, Vt = np.linalg.svd(B)
    D = np.diag([1, 1, np.sign(np.linalg.det(U@Vt))])
    return U@D@Vt

def rot_err(B):
    Rh = proj_SO3(B)
    c = (np.trace(Rh) - 1)/2   # R(0) = identity
    return np.arccos(np.clip(c, -1, 1))

def obj(params, N, OmQ, L, R):
    return -rot_err(B_of(build(params, 4, N, OmQ, L, R)))

def seed(N, bq, betaq):
    P = np.zeros((2, N, 7)); P[:, :, 1] = 1; P[:, :, 4] = 8
    tc = (np.arange(N)+0.5)/N
    for j in range(N):
        P[:, j, 5] = 8 if tc[j]*bq > betaq else -8
    return P.ravel()

if __name__ == '__main__':
    restarts = int(sys.argv[1]); N = int(sys.argv[2])
    rng = np.random.default_rng(7)
    for OmL, R in [(0.6, 3), (1.6, 1), (1.6, 10), (2.4, 5), (np.pi, 2), (np.pi, 50)]:
        L = 1.0; OmQ = OmL/2  # quaternion line-angle speed
        bq = OmQ*L; target = 2*delta(bq, R)
        best = 0; best_rand = 0
        seeds = [seed(N, bq, 2*delta(bq, R))] + [rng.normal(size=2*N*7)*rng.choice([0.5, 1.5, 3]) for _ in range(restarts)]
        for i, s in enumerate(seeds):
            r = minimize(obj, s, args=(N, OmQ, L, R), method='L-BFGS-B', options={'maxiter': 300})
            best = max(best, -r.fun)
            if i: best_rand = max(best_rand, -r.fun)
        print(json.dumps(dict(OmegaL=round(OmL, 4), R=R, bound_rot=round(target, 7), best=round(best, 7),
                              ratio=round(best/target, 7), ratio_random_only=round(best_rand/target, 7))), flush=True)
