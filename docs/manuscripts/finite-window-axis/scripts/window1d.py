"""Direction (a)+(c): exact minimax structure-tensor window in 1D.
Model: doubled-angle path psi(t)=2(theta(t)-theta(0)), |psi'|<=2*Omega; window g>=0, int g=1;
unknown contrast rho(t) in [1,R]; tensor J = int rho g e^{i psi} + e, |e| <= sigma*||g||_2 (additive,
contrast independent). Estimator arg(J)/2. Error(g) = (phi*-pi/2)/2, phi* first zero of
F(phi) = int g H(c_phi) + sigma||g||_2, H(x)=R x_+ + x_-, c_phi=cos((phi-B)_+), B=2 Omega|t|.
Claim: optimal delta* solves delta - sin(4 delta)/4 = sigma^2 Omega, g* ~ sin(2delta-2Omega|t|)_+, any R."""
import numpy as np, json
from scipy.optimize import brentq, minimize_scalar, minimize
out = {}
def F(phi, t, g, Om, sig, R, dt):
    B = 2*Om*np.abs(t); c = np.cos(np.clip(phi-B, 0, None))
    H = np.where(c > 0, R*c, c)
    return np.sum(g*H)*dt + sig*np.sqrt(np.sum(g*g)*dt)
def err(t, g, Om, sig, R):
    dt = t[1]-t[0]; g = g/(np.sum(g)*dt)
    f = lambda p: F(p, t, g, Om, sig, R, dt)
    if f(np.pi) > 0: return np.nan
    if f(np.pi/2) <= 0: return 0.0
    return (brentq(f, np.pi/2, np.pi, xtol=1e-13) - np.pi/2)/2
def dstar(Om, sig):
    return brentq(lambda d: d - np.sin(4*d)/4 - sig**2*Om, 1e-12, np.pi/4)
Om = 1.0
t = np.linspace(-20, 20, 400001)
# 1. box, sigma=0 vs closed form arctan
chk = []
for b in [0.3, 1.0, 1.5]:
    for R in [1, 4, 16]:
        L = b/Om; g = (np.abs(t) <= L/2).astype(float)
        e = err(t, g, Om, 0.0, R)
        cf = np.arctan(np.sqrt(R)*np.sin(b/2)/(1+np.sqrt(R)*np.cos(b/2)))
        chk.append([b, R, e, cf])
out['box_sigma0_vs_closed_form'] = chk
print('box vs closed form (b,R,num,cf):'); [print(' ', r) for r in chk]
# 2. optimal window and competitors
rows = []
for sig in [0.05, 0.2, 0.5]:
    d = dstar(Om, sig)
    gs = np.clip(np.sin(2*d - 2*Om*np.abs(t)), 0, None)*(np.abs(t) <= d/Om)
    row = {'sigma': sig, 'delta_star': d, 'small_noise_approx': (3*sig**2*Om/8)**(1/3)}
    for R in [1, 4, 16]:
        row[f'gstar_R{R}'] = err(t, gs, Om, sig, R)
        for name, shape in [('box', lambda s: (np.abs(t) <= s).astype(float)),
                            ('tri', lambda s: np.clip(1-np.abs(t)/s, 0, None)),
                            ('gauss', lambda s: np.exp(-t**2/(2*s*s)))]:
            res = minimize_scalar(lambda ls: (lambda v: 10 if np.isnan(v) else v)(err(t, shape(np.exp(ls)), Om, sig, R)),
                                  bounds=(np.log(1e-3), np.log(5)), method='bounded', options={'xatol': 1e-6})
            row[f'{name}_R{R}'] = res.fun; row[f'{name}_R{R}_scale'] = float(np.exp(res.x))
    rows.append(row)
    print({k: (round(v, 5) if isinstance(v, float) else v) for k, v in row.items() if 'scale' not in k})
out['optimal_vs_competitors'] = rows
json.dump(out, open(__import__('os').path.join(__import__('os').path.dirname(__file__), 'window1d.out.json'), 'w'), indent=1)
