# Worst-case axis error of a finite window with unknown weights

A short mathematical note, 26 November 2026. Draft for public release in the Scrolls repository.

**Status.** Interpretation (mathematics), not peer reviewed. The derivations were produced with AI agents (OpenAI Codex and Anthropic Claude). They were checked by a blind re-derivation by a separate agent, symbolic and 60-digit numeric checks, adversarial counterexample searches and the script in this folder. No human specialist has reviewed them, and there is no formal (Lean) proof. Nothing here uses scroll data, and nothing here is a statement about any real scan.

**In one paragraph.** A structure tensor, or any normalized average of doubled-angle phasors, reports the orientation at the center of its window. Inside the window the true orientation turns, and the weight each sample gets (gradient energy, contrast, depth response) is not known exactly. If the axis can turn at most $\Omega$ per unit length over a window of length $L$, and the weights vary by at most a factor $R$, the exact worst-case error of the half-argument estimate is

$$\delta(b,R)=\arg\left(1+\sqrt R\,e^{ib/2}\right)=\arctan\frac{\sqrt R\sin(b/2)}{1+\sqrt R\cos(b/2)},\qquad b=\Omega L,$$

no estimator that sees only the average can do better, and the formula is exact precisely when $b<\pi/2+\arccos(1-1/R)$. For $R=1$ it is $b/4$. The same number is the exact worst case in every dimension (principal eigenvector of an orientation tensor), for complex and quaternionic line fields, and, with $b$ halved and the result doubled, for the chordal mean of rotations. The 2D closed form coincides with a worked example in Klar's July 2026 paper on circular expectiles; the link is explained in section 2.

![Left: exact worst-case axis error against the total turn across the window, for weight ratios R = 1, 2, 4, 10 and 100, each curve ending where the error reaches 45 degrees and the formula stops holding. Right: the largest allowed turn across the window for a given allowed error, for the same R values.](figure.svg)

## 1. Setting and main result

Work on $[-L/2,L/2]$ with an unoriented axis angle $\theta(t)$ (defined modulo $\pi$), absolutely continuous, with $|\theta'(t)|\le\Omega$. A measurable weight $w$ satisfies $1\le w(t)\le R$; it is unknown, need not be symmetric, and may depend on the path. The reading is the normalized doubled-angle mean

$$m=\frac{\int w(t)\,e^{2i\theta(t)}\,dt}{\int w(t)\,dt}.$$

An estimator is any function of $m$. The error is the axis distance to $\theta(0)$, modulo $\pi$.

**Theorem 1.** Let $b=\Omega L$ and $R\ge1$, with $\sqrt R\,(\sin(b/2)-\cos(b/2))<1$; equivalently $b<b_{\max}(R)=\pi/2+\arccos(1-1/R)$ (for $R=1$, every $b<\pi$). Then

1. every admissible reading satisfies $|\arg m-2\theta(0)|\le 2\delta(b,R)$, so the estimate $\hat\theta=\tfrac12\arg m$ has error at most $\delta(b,R)$;
2. there are two admissible configurations with the same reading whose center axes are $2\delta(b,R)$ apart, so every estimator has worst-case error at least $\delta(b,R)$;
3. for $b\ge b_{\max}(R)$ some admissible configuration gives $m=0$ (at $b_{\max}$) or a reading pointing at the orthogonal axis, so an estimator that must always answer has worst-case error $\pi/2$. The domain is sharp.

Examples: for $b=60^\circ$, the error bound is $15^\circ$ at $R=1$ and $20.10^\circ$ at $R=4$. For $R=4$ the formula holds up to $b=131.4^\circ$.

**Window-length rule.** Inverting the formula, the largest full-window turn that keeps the error at most $D$ is $b=2D+2\arcsin(\sin D/\sqrt R)$ (as long as this stays in the domain). For $D=10^\circ$ and $R=4$ it is $29.96^\circ$. With a separately justified turning bound $\Omega$ this gives a maximal window length $L=b/\Omega$.

## 2. Relation to expectiles and circular expectiles

The linear version of this problem is known. For a random variable $X$ and $\tau\ge1/2$, the $\tau$-expectile equals the largest mean of $X$ under a reweighting whose density ratio is at most $\tau/(1-\tau)$: Delbaen ([arXiv:1307.5881](https://arxiv.org/abs/1307.5881), 2013, section 2, read 26 Nov 2026) gives the scenario set of the expectile as the measures with $a\le dQ/dP\le\frac{1-\tau}{\tau}a$ for the lower expectile. Density-ratio classes of this kind go back to DeRobertis and Hartigan ([Annals of Statistics 9(2), 1981](https://doi.org/10.1214/aos/1176345391)). Bellini, Klar, Mueller and Rosazza Gianin ([2014](https://doi.org/10.1016/j.insmatheco.2013.10.015), Proposition 8) give the same maximum over normalized densities with bounded largest-to-smallest ratio, with a two-level optimizer, and Cascos and Ochoa ([2021](https://doi.org/10.1016/j.jmva.2021.104757)) obtain support functions of multivariate expectile regions from expectiles of projections, which is the structure of the direction-by-direction step below.

Klar ([arXiv:2607.08306](https://arxiv.org/abs/2607.08306), 9 July 2026, read in full 26 Nov 2026) defines circular expectiles by an asymmetric chord-distance loss. Its first-order condition (from its definitions of $C^\pm_\nu$ and $S^\pm_\nu$), written with $\alpha$ and $1-\alpha$ as the two weights, is

$$\alpha\,E[\sin(X-\nu);X>\nu]+(1-\alpha)\,E[\sin(X-\nu);X\le\nu]=0 .$$

In the proof below, the extreme direction $\beta=2\delta$ solves exactly this equation with $\alpha/(1-\alpha)=R$, for $X$ uniform on the arc $[0,b]$ of reachable doubled angles. Klar's Example 7 solves it for $X\sim\mathrm{Unif}(-d,d)$:

$$\mu_\alpha=2\arctan\left(\frac{\sqrt\alpha-\sqrt{1-\alpha}}{\sqrt\alpha+\sqrt{1-\alpha}}\tan\frac d2\right).$$

With $d=b/2$ and $\alpha=R/(1+R)$ one has $2\delta(b,R)=b/2+\mu_\alpha$, an identity the check script verifies to machine precision. So the 2D closed form is Klar's uniform-arc example, read through the circular analogue of the expectile's density-ratio representation. Klar's paper does not discuss worst cases, density ratios, axial data or higher dimensions.

What this note adds, as far as the search below found:

- the worst-case reading of a weighted circular mean under bounded turning and a bounded density ratio, as an exact minimax statement with matching lower bound;
- the reduction showing the worst case is the uniform reach distribution, and the sharp domain $b<b_{\max}(R)$;
- noise and general weight envelopes (section 4);
- the extension to every dimension, to $\mathbb{CP}^{d-1}$ and $\mathbb{HP}^{d-1}$ and to rotations (section 5);
- the minimax window for a structure tensor (section 6), whose small-noise limit is classical.

## 3. Proof of Theorem 1

Rotate so that $\theta(0)=0$ and write $q=2\theta$. Then $|q(t)|\le B(t)=2\Omega|t|$; only this pointwise reach is used for the upper bound. Under the depth coordinate, $B$ is uniform on $[0,b]$ on each half of the window.

**Support function.** For a direction $\nu$, the reading can have argument $\nu$ or more only if $\sup\int w\sin(q-\nu)\ge0$. At each $t$ the supremum over $|q|\le B(t)$ is attained at $q=B(t)$ when $B(t)\le\nu+\pi/2$, and the supremum over weights takes $w=R$ where $\sin(B-\nu)>0$ and $w=1$ elsewhere. For $\nu\in[b/2,b]$ this gives, up to the factor $1/\Omega$,

$$\Phi(\nu)=R\int_\nu^b\sin(B-\nu)\,dB+\int_0^\nu\sin(B-\nu)\,dB=R\,(1-\cos(b-\nu))-(1-\cos\nu).$$

$\Phi(0)>0$ and $\Phi'(\nu)=-R\sin(b-\nu)-\sin\nu<0$, so $\Phi$ has a unique zero $\beta$. Writing $1-\cos x=2\sin^2(x/2)$ turns $\Phi(\beta)=0$ into $\sqrt R\sin((b-\beta)/2)=\sin(\beta/2)$, that is $\tan(\beta/2)=\sqrt R\sin(b/2)/(1+\sqrt R\cos(b/2))$, so $\beta=2\delta(b,R)$. For $\nu\in(\beta,\pi]$ the same computation, with the clip $q\le\nu+\pi/2$ when $b>\nu+\pi/2$, stays negative: at $\nu=\pi/2$ it equals $R(1-\sin b)-1$, which is negative exactly on the domain, and the support value is nonincreasing in $\nu$. Hence every reading has $|\arg m|\le\beta$, by symmetry under $q\to-q$. This is part 1.

**Witness pair.** Take $\theta_1(t)=\Omega|t|$ and $\theta_2(t)=\beta-\Omega|t|$, both with $w=R$ where $2\Omega|t|>\beta$ and $w=1$ elsewhere. Both are admissible. For the first, $\mathrm{Im}(e^{-i\beta}m_1)\propto\Phi(\beta)=0$ and the real part is positive, so $m_1=|m_1|e^{i\beta}$. For the second, $m_2=e^{2i\beta}\overline{m_1}=m_1$. The centers $0$ and $\beta$ are $\beta=2\delta$ apart, so any estimator errs by at least $\delta$ on one of them. This is part 2, and the first configuration shows the half-argument estimate attains the bound.

**Sharpness of the domain.** Take the linear twist $\theta(t)=\Omega t$ (the two halves turn in opposite directions) with $w=R$ where $2\Omega|t|>\pi/2$ and $w=1$ elsewhere. By symmetry $m$ is real, and $\mathrm{Re}\,m\propto 1+R(\sin b-1)$, which is zero at $b_{\max}$ and negative beyond it. A negative real reading points at the orthogonal axis.

## 4. Noise and general weight envelopes

Let the weight satisfy $\ell(t)\le w(t)\le u(t)$ for known even envelopes with $\int\ell>0$, let the turning allowance be an even envelope $\omega(t)$ with $B(t)=2\int_0^{|t|}\omega$, and add a reading error $|e|\le\eta$ with $\eta<1$, applied after normalization. Define, for $\phi\in[0,\pi]$,

$$c_\phi(t)=\cos((\phi-B(t))_+),\qquad F_\eta(\phi)=\int\left\lbrace u\,[c_\phi+\eta]_++\ell\,[c_\phi+\eta]_-\right\rbrace dt .$$

$F_\eta$ is continuous and nonincreasing, and $F_\eta(\pi/2)\ge0$. **Theorem 2.** If $F_\eta(\pi)<0$, let $\phi_*$ be the unique zero of $F_\eta$ in $[\pi/2,\pi)$. The exact minimax error for one reading is $(\phi_*-\pi/2)/2$, attained by half the argument. The proof is the support argument of section 3 with aligned noise added. For $R=1$ and constant $\Omega$ it gives $\delta=\tfrac12\lbrace b/2+\arcsin[\eta/\mathrm{sinc}(b/2)]\rbrace$ when $\eta<\mathrm{sinc}(b)$.

If $F_\eta(\pi)\ge0$, some admissible configuration gives a zero reading for every center axis, so a forced-output estimator has worst case $\pi/2$. This note makes no claim about rules that abstain on small readings. An earlier draft proposed abstaining only at a zero reading; that rule fails, because noise can carry a small nonzero reading to any axis (for example $b=60^\circ$, $\ell=u=1$, $\eta=0.9$ admits the reading $0.01$ for every axis).

Assumptions to keep in view: the noise ball is isotropic and applies after normalization; the envelopes and the turning allowance are known; the window is symmetric about the point being estimated.

## 5. Every dimension, complex and quaternionic lines, rotations

**Theorem 3.** Let $K$ be $\mathbb R$, $\mathbb C$ or $\mathbb H$ and $d\ge2$. Let $t\mapsto[n(t)]$ be a path of lines in $K^d$ with $\mathrm{dist}(n(t),n(s))\le\Omega|t-s|$, where $\mathrm{dist}(x,y)=\arccos|\langle x,y\rangle|$, and let $1\le w\le R$. Put $M=\int w\,nn^*/\int w$. On the domain of Theorem 1, the top eigenvalue of $M$ is simple, its eigenvector is within $\delta(b,R)$ of $n(0)$, and two admissible data sets with the same $M$ have centers $2\delta(b,R)$ apart. So $\delta(b,R)$ is the exact minimax error over estimators that see $M$, in every dimension and for each $K$.

*Proof outline.* (i) For unit $a,u$ with $\mathrm{dist}(a,u)=\chi$ and $n$ within $\rho$ of $a$, $|\langle u,n\rangle|^2-|\langle a,n\rangle|^2\le\sin\chi\,\sin(2\rho-\chi)$ when $2\rho\le\chi+\pi/2$, with equality on a real great circle. (ii) Integrating this with the bang-bang weight gives $\int w(|\langle u,n\rangle|^2-|\langle n_0,n\rangle|^2)\le(\sin\chi/\Omega)\,\Phi(\chi)<0$ for every $u$ at distance $\chi\in(\beta,\pi/2]$ from $n_0$. At $\chi=\pi/2$ this is a strict gap $e^*Me<n_0^*Mn_0$ for every $e\perp n_0$. (iii) If $v$ is a top eigenvector at distance $\psi$ from $n_0$, the quadratic form on the real great circle through $n_0$ and $v$ is a sinusoid in $2\chi$ with positive amplitude by the gap, which forces $\psi<\pi/4$ and gives a point $u$ at distance $2\psi$ with the same value as $n_0$; step (ii) then forces $2\psi\le\beta$. The gap also rules out a repeated top eigenvalue. (iv) The planar witness pair of section 3, embedded in a real 2-plane, gives the lower bound, since $M$ is then an affine function of the planar reading.

**Corollary (rotations).** Rotation paths with $\angle(\mathrm{Rot}(t)^T\mathrm{Rot}(s))\le\Omega|t-s|$ correspond to quaternion lines in $\mathbb{RP}^3$ with speed $\Omega/2$, and the chordal $L_2$ mean (the closest rotation to $\int w\,\mathrm{Rot}$, equivalently Davenport's q-method) is the top eigenvector of the quaternion matrix ([Markley, Cheng, Crassidis and Oshman 2007](https://doi.org/10.2514/1.28949)). Its exact worst-case rotation error is $2\delta(\Omega L/2,R)$, valid for all $R$ when $\Omega L\le\pi$.

**Corollary (pure states).** With $K=\mathbb C$ this is the statement for pure states of $\mathbb C^d$ under the Fubini-Study distance: the principal eigenvector of a weighted mixture of slowly varying pure states is within $\delta(b,R)$ of the center state, and this is sharp.

The full proof is in [projective-proof.md](projective-proof.md). Numerical checks ([scripts/](scripts/)): an adversarial search over 25 cases inside the domain ($\mathbb{RP}^2$, $\mathbb{RP}^3$, $\mathbb{CP}^2$, $\mathbb{HP}^1$, $SO(3)$) found nothing above the bound (best ratio 1.0000000) and two cases outside it showed the predicted failure. One quaternionic case did not converge (ratio 0.915), which does not affect the bound. Outside the domain, the minimax value over all estimators is not computed.

## 6. The minimax window for a structure tensor

Let a window $g$ (real, signed weights allowed) average doubled-angle phasors over points $x$ at distance $d(0,x)$, with turning reach $2d(0,x)$, unknown contrast in $[1,R]$ multiplying $g$, and a per-sample perturbation of total energy at most $\sigma^2$, so the windowed perturbation has size at most $\sigma\|g\|_2$. Let $q_\delta(x)=\max(0,\sin(2\delta-2d(0,x)))$.

**Theorem 4.** Let $\delta_*<\pi/4$ solve $\|q_\delta\|_2=\sigma$. No window certifies a center error below $\delta_*$, for any $R$, and $g\propto q_{\delta_*}$ attains $\delta_*$ for every $R$.

*Proof.* At the support direction $\pi/2+2\delta_*$, every sample's best projection is at least $-g\,q_{\delta_*}$, so the support value is at least $-\langle g,q_{\delta_*}\rangle+\sigma\|g\|\ge\|g\|(\sigma-\|q_{\delta_*}\|)=0$ by Cauchy-Schwarz. For $g\propto q_{\delta_*}$ every sample with nonzero weight has a negative projection, so the contrast never helps the adversary, and equality holds.

On a line with turning rate $\Omega$ the condition is $\delta-\tfrac14\sin4\delta=\sigma^2\Omega$, so $\delta_*\approx(3\sigma^2\Omega/8)^{1/3}$ for small noise, with a sine-triangle window of half-width $\delta_*/\Omega$. In a numerical comparison ([scripts/window1d.py](scripts/window1d.py)) the best Gaussian window is 0.4 to 3 percent worse and the best box about 4 percent worse. With curvature $K$ along the sheet and spacing change $W$ across it, the optimal window is an anisotropic sine-cone reaching $\delta_*/K$ along and $\delta_*/W$ across.

In the small-noise limit this is classical optimal recovery: triangular kernels are minimax for Lipschitz classes ([Sacks and Ylvisaker 1978](https://doi.org/10.1214/aos/1176344315); [Donoho 1994](https://doi.org/10.1214/aos/1176325367)). What may be new is the exact circular version, its immunity to unknown contrast, and the scale and aspect rule. The geometry is first order: it treats turning as a bound on reach, not as a sheet frame that rotates.

## 7. What is borrowed and what is not claimed

- **Borrowed.** Density-ratio classes (DeRobertis and Hartigan 1981); the expectile as an extreme reweighted mean (Delbaen 2013 and the references there; [Bellini, Klar, Mueller and Rosazza Gianin 2014](https://doi.org/10.1016/j.insmatheco.2013.10.015), Proposition 8); expectile regions through projections (Cascos and Ochoa 2021); circular expectiles and the uniform-arc closed form ([Klar 2026](https://arxiv.org/abs/2607.08306)); bounded-curvature reachability ([Cockayne and Hall 1975](https://doi.org/10.1137/0313012)); the structure tensor and doubled-angle representation (Bigun and Granlund 1987; Kass and Witkin 1987); quaternion averaging (Markley et al. 2007); optimal recovery kernels (Sacks and Ylvisaker 1978; Donoho 1994).
- **Figure.** [figure.svg](figure.svg), drawn by [figure.py](figure.py) from the closed forms: the bound against the total turn for several $R$, and the window-length rule.
- **Possibly new, priority not established.** The exact minimax statement of section 1 with its lower bound and sharp domain; the dimension-free, complex, quaternionic and rotation forms; the contrast immunity of the optimal window. Searches on 26 Nov 2026 (circular robust statistics, robust Bayes for directions, structure-tensor bias, Davis-Kahan-type eigenvector bounds, rotation averaging) found no prior statement. They were web and abstract searches, not an exhaustive bibliographic review; a specialist in directional statistics or robust statistics may know one.
- **Not claimed.** That any real CT window satisfies these hypotheses with known $\Omega$, $R$ or $\eta$; that the bound has been tested on real scans; any statement about reading a scroll. A test on synthetic scrolls (ScrollSim) is preregistered and has not been run.

## 8. Reproduce

```bash
python docs/manuscripts/finite-window-axis/check.py
```

`check.py` needs only numpy and takes a few seconds. It checks the closed form against a direct root of the support condition, the identity with Klar's Example 7, a random search over piecewise-linear paths and weights (no reading may exceed the bound), the witness pair, the failure just outside the domain, and a control: the same search must exceed 98 percent of the bound, so a search too weak to reach the bound fails. Exit code 0 means every check passed. The scripts in [scripts/](scripts/) need numpy and scipy: `search.py D RESTARTS CELLS SEED` (real line fields in dimension D), `so3search.py RESTARTS CELLS`, `kpsearch.py RESTARTS CELLS` (complex and quaternionic lines), and `window1d.py` (the window comparison).

## Citation

Chase Hendrick, *Worst-case axis error of a finite window with unknown weights*, Scrolls repository note, 26 November 2026, https://github.com/ChaseHendrick/Scrolls/tree/main/docs/manuscripts/finite-window-axis. Derived with AI assistance; see Status.
