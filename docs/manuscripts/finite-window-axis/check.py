"""Numerical checks for the finite-window axis bound (docs/manuscripts/finite-window-axis).

Each check can fail. It prints one line per check and a JSON summary, and exits 1 if any check fails.

  python docs/manuscripts/finite-window-axis/check.py          # about 3 s on one CPU core
  python docs/manuscripts/finite-window-axis/check.py --json   # summary only

Checks:
  1. closed form: delta(b, R) equals the root of the support condition, found by bisection on a fine grid;
  2. expectile form: 2 delta - b/2 equals the circular expectile of Unif(-b/2, b/2) at level R/(1+R)
     (Klar 2026, Example 7);
  3. random search: piecewise-constant turning paths with weights in [1, R] never give a reading whose
     half-argument exceeds delta (a counterexample would fail the check);
  4. witness pair: two admissible configurations with centers 2 delta apart give the same reading;
  5. domain: just outside b_max(R) a linear twist with a step weight gives a reading with negative
     real part (error pi/2), so the formula cannot hold there;
  6. control: the same search with the bound deliberately shrunk by 2 percent must find violations.
"""
import argparse
import json
import math
import sys

import numpy as np


def delta(b, R):
    return math.atan2(math.sqrt(R) * math.sin(b / 2), 1 + math.sqrt(R) * math.cos(b / 2))


def b_max(R):
    return math.pi / 2 + math.acos(1 - 1 / R)


def support_root(b, R, n=200000):
    """Largest doubled angle beta with max over weights of sum w sin(B - beta) >= 0, B ~ Unif[0, b]."""
    B = (np.arange(n) + 0.5) / n * b
    lo, hi = 0.0, math.pi
    for _ in range(80):
        beta = (lo + hi) / 2
        q = np.minimum(B, beta + math.pi / 2)
        v = np.sin(q - beta)
        if (np.where(v > 0, R, 1.0) * v).sum() >= 0:
            lo = beta
        else:
            hi = beta
    return lo / 2


def klar_expectile(d, alpha):
    a, c = math.sqrt(alpha), math.sqrt(1 - alpha)
    return 2 * math.atan((a - c) / (a + c) * math.tan(d / 2))


def reading(rates, weights, b):
    """Doubled-angle reading for a path on [-1/2, 1/2] made of cells with turning rates in [-1, 1]
    (in units of Omega) and one weight per cell. Exact cell integrals of exp(i q)."""
    n = len(rates)
    h = 1.0 / n
    # integrate theta' = Omega * rate from the center outward; doubled angle q = 2 theta
    half = n // 2
    q_edges = np.zeros(n + 1)
    for k in range(half, n):
        q_edges[k + 1] = q_edges[k] + 2 * b * rates[k] * h
    for k in range(half - 1, -1, -1):
        q_edges[k] = q_edges[k + 1] - 2 * b * rates[k] * h
    m = 0j
    for k in range(n):
        a0, a1 = q_edges[k], q_edges[k + 1]
        if abs(a1 - a0) < 1e-12:
            seg = h * np.exp(1j * a0)
        else:
            seg = h * (np.exp(1j * a1) - np.exp(1j * a0)) / (1j * (a1 - a0))
        m += weights[k] * seg
    return m / (np.sum(weights) * h)


def search(b, R, rng, trials, cells=24):
    worst = 0.0
    for _ in range(trials):
        kind = rng.integers(3)
        if kind == 0:
            rates = rng.uniform(-1, 1, cells)
        elif kind == 1:
            rates = np.sign(rng.uniform(-1, 1, cells))
        else:  # V paths and their perturbations, near the extremal configuration
            rates = np.concatenate([-np.ones(cells // 2), np.ones(cells // 2)])
            rates = np.clip(rates + rng.normal(0, 0.2, cells), -1, 1)
        if rng.random() < 0.5:
            weights = rng.uniform(1, R, cells)
        else:
            weights = np.where(rng.random(cells) < 0.5, 1.0, R)
        m = reading(rates, weights, b)
        worst = max(worst, abs(math.atan2(m.imag, m.real)) / 2)
    # the extremal V path with its step weight, on the same grid
    rates = np.concatenate([-np.ones(cells // 2), np.ones(cells // 2)])
    t = np.abs((np.arange(cells) + 0.5) / cells - 0.5)
    weights = np.where(b * 2 * t > 2 * delta(b, R), R, 1.0)
    m = reading(rates, weights, b)
    worst = max(worst, abs(math.atan2(m.imag, m.real)) / 2)
    return worst


def main(argv=None):
    if sys.stdout.isatty():  # the Scrolls look (AGENTS.md rule 17), when run inside a checkout
        try:
            from kit import termstyle
            termstyle.script()
        except ImportError:
            pass
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--json", action="store_true", help="print only the JSON summary")
    p.add_argument("--seed", type=int, default=20261126)
    p.add_argument("--trials", type=int, default=3000)
    a = p.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    settings = [(0.3, 1), (math.pi / 3, 1), (math.pi / 3, 4), (1.0, 10), (math.pi / 2, 9), (2.0, 4), (2.6, 1.5)]
    out = {"settings": [], "pass": True}

    for b, R in settings:
        d = delta(b, R)
        row = {"b": b, "R": R, "delta_deg": math.degrees(d)}
        row["closed_vs_root_deg"] = abs(math.degrees(d - support_root(b, R)))
        row["closed_ok"] = row["closed_vs_root_deg"] < 1e-3
        row["expectile_gap"] = abs((2 * d - b / 2) - klar_expectile(b / 2, R / (1 + R)))
        row["expectile_ok"] = row["expectile_gap"] < 1e-12
        worst = search(b, R, rng, a.trials)
        row["search_worst_deg"] = math.degrees(worst)
        row["search_ok"] = worst <= d + 1e-9
        shrunk = search(b, R, rng, a.trials // 3) > 0.98 * d
        row["control_ok"] = bool(shrunk)
        # witness pair: theta1 = Omega|t| (center 0), theta2 = beta - Omega|t| (center beta = 2 delta),
        # same step weight; the two readings must coincide
        beta = 2 * d
        n = 20000
        t = (np.arange(n) + 0.5) / n - 0.5
        w = np.where(2 * b * np.abs(t) > beta, R, 1.0)
        m1 = np.sum(w * np.exp(2j * b * np.abs(t))) / w.sum()
        m2 = np.sum(w * np.exp(2j * (beta - b * np.abs(t)))) / w.sum()
        row["witness_gap"] = abs(m1 - m2)
        row["witness_ok"] = row["witness_gap"] < 1e-3 and abs(math.atan2(m1.imag, m1.real) - beta) < 1e-3
        out["settings"].append(row)

    dom = []
    for R in (1.5, 4, 12):
        b = b_max(R) * 1.02
        if b >= math.pi:
            continue
        n = 20000
        t = (np.arange(n) + 0.5) / n - 0.5
        w = np.where(2 * b * np.abs(t) > math.pi / 2, R, 1.0)
        m = np.sum(w * np.exp(2j * b * t)) / w.sum()  # linear twist: the two halves turn opposite ways
        dom.append({"R": R, "b": b, "re_m": float(m.real), "ok": bool(m.real < 0)})
    out["domain"] = dom

    checks = ["closed_ok", "expectile_ok", "search_ok", "control_ok", "witness_ok"]
    for row in out["settings"]:
        out["pass"] &= all(row[c] for c in checks)
    out["pass"] &= all(r["ok"] for r in dom)
    if not a.json:
        for row in out["settings"]:
            flags = " ".join(f"{c[:-3]}={'PASS' if row[c] else 'FAIL'}" for c in checks)
            print(f"b={row['b']:.4f} R={row['R']:<4} delta={row['delta_deg']:.4f} deg "
                  f"search worst={row['search_worst_deg']:.4f} deg  {flags}")
        for r in dom:
            print(f"outside domain R={r['R']} b={r['b']:.4f}: Re m = {r['re_m']:.4f} ({'PASS' if r['ok'] else 'FAIL'})")
        print("ALL PASS" if out["pass"] else "SOME CHECK FAILED")
    print(json.dumps({"pass": out["pass"], "n_settings": len(settings), "n_domain": len(dom)}))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
