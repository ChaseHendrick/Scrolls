"""Adversarial search for Corollary C: CP^2 (C^3 = R^6) and HP^1 (H^2 = R^8).

A unit vector of K^m is stored as a real vector of length D = dim_R K * m.
|<x,n>_K|^2 = sum_k (x . J_k n)^2 with J_k the real matrices of right
multiplication by the units of K, so x* M x = x^T Q x with
Q = int w sum_k (J_k n)(J_k n)^T / int w. Cells are great circle arcs of S^{D-1}
with arc <= Omega*dur; since d_FS <= d_sphere this is a subset of the
admissible class. Integrals are closed form per cell.
"""
import numpy as np, sys, json
from scipy.optimize import minimize
from search import build, delta, arc_nnT

def blocks(K, m):
    if K == 'C':
        u = [np.eye(2), np.array([[0, -1], [1, 0]])]
    else:
        I = np.eye(4)
        Ri = np.array([[0, -1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1], [0, 0, -1, 0]], float)
        Rj = np.array([[0, 0, -1, 0], [0, 0, 0, -1], [1, 0, 0, 0], [0, 1, 0, 0]], float)
        Rk = np.array([[0, 0, 0, -1], [0, 0, 1, 0], [0, -1, 0, 0], [1, 0, 0, 0]], float)
        u = [I, Ri, Rj, Rk]
    return [np.kron(np.eye(m), J) for J in u]

def check_blocks(Js, K):
    # sanity: J_k orthogonal, and sum_k (J_k n)(J_k n)^T is a projector of rank dim K
    rng = np.random.default_rng(0)
    n = rng.normal(size=Js[0].shape[0]); n /= np.linalg.norm(n)
    P = sum(np.outer(J@n, J@n) for J in Js)
    assert np.allclose(P@P, P) and round(np.trace(P)) == len(Js), K

def Q_of(cells, Js):
    D = Js[0].shape[0]; Q = np.zeros((D, D)); W = 0
    for (p, c, ell, dur, w) in cells:
        for J in Js:
            Q += w*arc_nnT(J@p, J@c, ell, dur)
        W += w*dur
    return Q/W

def err(Q, Js):
    ev, V = np.linalg.eigh(Q); v = V[:, -1]
    e1 = np.zeros(len(v)); e1[0] = 1
    ov = np.sqrt(sum((v@(J@e1))**2 for J in Js))
    return np.arccos(min(1, ov))

def obj(params, D, N, Om, L, R, Js):
    return -err(Q_of(build(params, D, N, Om, L, R), Js), Js)

if __name__ == '__main__':
    restarts = int(sys.argv[1]); N = int(sys.argv[2])
    rng = np.random.default_rng(3)
    for K, m in [('C', 3), ('H', 2)]:
        Js = blocks(K, m); check_blocks(Js, K); D = Js[0].shape[0]
        for b, R in [(0.8, 5), (np.pi/2, 3), (2.0, 4)]:
            L = 1.0; Om = b; dl = delta(b, R)
            best = 0
            for i in range(restarts):
                s = rng.normal(size=2*N*(D+3))*rng.choice([0.5, 1.5, 3])
                r = minimize(obj, s, args=(D, N, Om, L, R, Js), method='L-BFGS-B', options={'maxiter': 300})
                best = max(best, -r.fun)
            print(json.dumps(dict(space=f'{K}P^{m-1}', b=round(b, 4), R=R, delta=round(dl, 7),
                                  best_random=round(best, 7), ratio=round(best/dl, 7))), flush=True)
