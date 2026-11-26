# Appendix: full proof of the dimension-free extension

Part of [Worst-case axis error of a finite window with unknown weights](README.md). This is the proof as written by the AI agent that derived it, lightly edited for release. "The sketch" below refers to an earlier unpublished outline whose steps (ii) and (iii) this proof corrects and replaces. The search scripts are in [scripts/](scripts/); their output files are not included, and the table in section 9 records one run.


Status: proved below for line fields in RP^{d-1}, CP^{d-1} and HP^{d-1} (all d >= 2), and for SO(3) through unit quaternions. The proof replaces step (iii) of the proposed sketch (the homotopy) by a two-by-two argument and corrects the pointwise formula of step (ii). It also shows that the domain b <= pi/2 is not the natural one: the result holds, in every dimension, on the larger domain D defined in section 1, which is also where the 2D formula holds. Numerical checks are in `scripts/search.py`, `scripts/so3search.py` and `scripts/kpsearch.py`.

## 1. Setting and statement

Let K be R, C or H, and V = K^d with d >= 2, with the inner product <x,y> = sum conj(x_i) y_i (scalars act on the right). For unit vectors x, y the ray distance is

  dist(x, y) = arccos |<x, y>|, a value in [0, pi/2].

It is the geodesic distance of the Fubini-Study metric normalized so that a projective line has length pi (for K = R it is the line angle on RP^{d-1}). It depends only on the rays of x and y, and it is a metric.

Admissible data on [-L/2, L/2]:
- a path of rays t -> [n(t)] with dist(n(t), n(s)) <= Omega |t - s| (this is implied by geodesic speed at most Omega, and is all the proof uses);
- a measurable weight w with 1 <= w(t) <= R.

Write n0 = n(0), P(t) = n(t) n(t)* (well defined on rays, continuous in t), and

  M = int w P dt / int w dt, a Hermitian matrix over K with trace 1.

The estimate is any unit maximizer v of x* M x over the unit sphere (a principal eigenvector). Put b = Omega L and

  delta(b, R) = arctan( sqrt(R) sin(b/2) / (1 + sqrt(R) cos(b/2)) ).

Domain: D = { (b, R) : 0 < b < pi, R >= 1, sqrt(R) (sin(b/2) - cos(b/2)) < 1 }. It contains every b <= pi/2 for every R, because then sin(b/2) <= cos(b/2). On D one has delta(b, R) < pi/4, and D is exactly the set of b < pi where delta(b, R) < pi/4 (since tan delta < 1 is the same inequality).

**Theorem.** For (b, R) in D and every d >= 2 and K in {R, C, H}:
1. For all admissible data, the principal eigenvalue of M is simple and every principal eigenvector v satisfies dist(v, n0) <= delta(b, R).
2. There are two admissible data sets with the same M whose centers n0 are at distance 2 delta(b, R). Hence every estimator that is a function of M has worst-case error at least delta(b, R).

So the exact minimax worst-case error, over estimators that see only M, is delta(b, R), it does not depend on d or on K, and it is attained by the principal eigenvector.

**Corollary B (SO(3)).** Let t -> Rot(t) be a rotation path whose rotation-angle distance obeys angle(Rot(t)^T Rot(s)) <= Omega |t - s|, weights in [1, R], and let the estimate be any maximizer of tr(Q^T int w Rot dt) over Q in SO(3) (the chordal L2 mean). If (Omega L / 2, R) lies in D, in particular whenever Omega L <= pi, the exact minimax worst-case rotation-angle error is 2 delta(Omega L / 2, R), attained by the chordal mean, which is unique.

**Corollary C (pure states).** The theorem with K = C is the statement for pure states of C^d (projectors P(t), Fubini-Study distance arccos |<psi, phi>|); K = H gives HP^{d-1}. For a qubit (CP^1) the Fubini-Study distance is half the Bloch-sphere angle, so for Bloch vectors moving at angular speed at most Omega_B the error of the mean Bloch direction is at most 2 delta(Omega_B L / 2, R), and this is sharp.

## 2. The scalar function Phi

For 0 <= chi <= pi/2 define

  Phi(chi) = R (1 - cos(b - chi)) - (1 - cos chi)   for chi <= b,
  Phi(chi) = cos chi - cos(chi - b)                 for chi > b (only possible when b < pi/2).

**Lemma 2.1.** Let (b, R) be in D. There is a unique beta in [b/2, min(b, pi/2)) with Phi(beta) = 0, Phi > 0 on [0, beta) and Phi < 0 on (beta, pi/2]. Moreover beta = 2 delta(b, R).

Proof. Phi(0) = R (1 - cos b) > 0. On (0, min(b, pi/2)) the derivative is -R sin(b - chi) - sin chi < 0, since b - chi lies in (0, pi). If b < pi/2, then Phi(b) = -(1 - cos b) < 0, and for chi in (b, pi/2], cos chi - cos(chi - b) < 0 because 0 < chi - b < chi <= pi/2. If b >= pi/2, then Phi(pi/2) = R (1 - sin b) - 1 = R (sin(b/2) - cos(b/2))^2 - 1 < 0 on D. This gives a unique root beta below min(b, pi/2) with the stated signs. Phi(b/2) = (R - 1)(1 - cos(b/2)) >= 0 gives beta >= b/2. For the closed form, 1 - cos x = 2 sin^2(x/2) turns Phi(beta) = 0 into R sin^2((b - beta)/2) = sin^2(beta/2), and both sines are nonnegative because (b - beta)/2 lies in [0, pi/2) and beta/2 in (0, pi/4). So sqrt(R) sin(b/2 - beta/2) = sin(beta/2), which rearranges to tan(beta/2) = sqrt(R) sin(b/2) / (1 + sqrt(R) cos(b/2)); the denominator is positive since b < pi. QED.

## 3. The pointwise planar bound (corrects step (ii))

For unit x write f_x(t) = |<x, n(t)>|^2, so x* M x = int w f_x / int w.

**Lemma 3.1.** Let a, u be unit vectors with dist(a, u) = chi in [0, pi/2], and n a unit vector with dist(a, n) <= rho, rho in [0, pi/2]. Then

  |<u, n>|^2 - |<a, n>|^2 <= G_chi(rho) := max over theta in [0, rho] of [cos^2(theta - chi) - cos^2 theta] = max over theta in [0, rho] of sin chi sin(2 theta - chi).

Equality holds for n = a cos rho + e sin rho when 2 rho <= chi + pi/2, where e is defined below; so the maximum over the ball is attained on one real great circle.

Proof. Replace u by u lambda with |lambda| = 1 (this does not change the ray) so that <a, u> = cos chi is real and nonnegative; then u = a cos chi + e sin chi with e a unit vector orthogonal to a (if chi = pi/2 take e = u). Write n = a alpha + e beta' + f with f orthogonal to a and e, so |alpha|^2 + |beta'|^2 <= 1 and |alpha| = cos theta with theta = dist(a, n) <= rho. Since cos chi and sin chi are real, <u, n> = cos chi alpha + sin chi beta', so

  |<u, n>| <= cos chi |alpha| + sin chi sqrt(1 - |alpha|^2) = cos(chi - theta).

Hence the difference is at most cos^2(chi - theta) - cos^2 theta = sin chi sin(2 theta - chi). QED.

Remark (gap in the sketch). The sketch claims the ball maximum is cos^2((chi - rho)_+) - cos^2(rho), from the triangle inequality. That is the true value when rho <= chi but not when rho > chi: for chi = 0.1, rho = 0.5 it gives 0.2298, while the true maximum is 0.0782. The bound is never used with rho > chi in the proof below (there rho <= b/2 <= beta < chi), so the error is harmless, but Lemma 3.1 is the correct statement and it also covers K = C, H.

When 2 rho <= chi + pi/2 the function theta -> sin chi sin(2 theta - chi) is nondecreasing on [0, rho], so G_chi(rho) = sin chi sin(2 rho - chi).

**Lemma 3.2 (support bound).** Let (b, R) be in D, let a = n0, and let u be a unit vector with chi = dist(n0, u) in (beta, pi/2]. Then int w (f_u - f_{n0}) dt < 0 for all admissible data.

Proof. By admissibility dist(n(t), n0) <= rho(t) = Omega |t| <= b/2. Since b < pi and beta >= b/2, we have 2 rho(t) <= b <= chi + pi/2, so pointwise f_u - f_{n0} <= g(t) := sin chi sin(2 Omega |t| - chi). Because 1 <= w <= R, w g <= R g_+ - g_-. Substituting T = 2 Omega |t| (both halves of the interval),

  int w (f_u - f_{n0}) dt <= (1/Omega) int_0^b [R (sin chi sin(T - chi))_+ - (sin chi sin(T - chi))_-] dT.

On [0, b] one has T - chi in [-chi, b - chi], inside (-pi/2, pi/2) because chi <= pi/2 and b - chi <= b/2 < pi/2, so sin(T - chi) has the sign of T - chi. The right side therefore equals (sin chi / Omega) Phi(chi), which is negative by Lemma 2.1. QED.

Taking chi = pi/2 (u = e orthogonal to n0):

**Corollary 3.3 (gap).** For every unit e orthogonal to n0, e* M e < n0* M n0. (For b <= pi/2 this is also immediate pointwise: f_{n0} - f_e >= cos^2 rho - sin^2 rho = cos 2 rho >= 0, strictly for |t| < L/2.)

## 4. Proof of the theorem, part 1 (replaces steps (i) and (iii))

Let v be a unit maximizer of x* M x and psi = dist(v, n0). If psi = 0 there is nothing to prove. Otherwise rephase v so that <n0, v> = cos psi > 0 and write v = n0 cos psi + e sin psi with e a unit vector orthogonal to n0. On the real great circle x(chi) = n0 cos chi + e sin chi,

  h(chi) = x(chi)* M x(chi) = (A + B)/2 + ((A - B)/2) cos 2chi + c sin 2chi,

with A = n0* M n0, B = e* M e, c = Re(n0* M e) (M is Hermitian, so the two cross terms add to 2 c sin chi cos chi). By Corollary 3.3, A > B, so h is a sinusoid in 2 chi with positive amplitude whose maxima are exactly the chi congruent mod pi to chi0, where 2 chi0 = atan2(2c, A - B) lies in (-pi/2, pi/2). Since v = x(psi) maximizes x* M x on the whole sphere, it maximizes h, so psi is congruent to chi0 mod pi. As psi is in (0, pi/2] and chi0 in (-pi/4, pi/4), psi = chi0 < pi/4.

This is the step the sketch handled with a homotopy. The homotopy is not needed: the strict gap of Corollary 3.3 already forbids a principal eigenvector at distance >= pi/4 from n0, with no continuity argument, and it does so for each data set separately.

Now h is symmetric about psi, so u = x(2 psi) has u* M u = h(2 psi) = h(0) = n0* M n0 (this is step (i) of the sketch; it is valid for every psi, but only psi < pi/4 is needed). Because 2 psi < pi/2, dist(u, n0) = arccos |cos 2 psi| = 2 psi. Thus int w (f_u - f_{n0}) = 0, and Lemma 3.2 forces 2 psi <= beta, that is psi <= beta/2 = delta(b, R).

Simplicity of the top eigenvalue. Hermitian matrices over R, C and H have a spectral theorem (real right eigenvalues, an orthonormal eigenbasis; for H see F. Zhang, Linear Algebra Appl. 251 (1997) 21-57). The unit maximizers are the unit vectors of the top eigenspace E. If dim_K E >= 2, E contains a unit vector orthogonal to n0, which would be a maximizer at distance pi/2 > delta. So E is one-dimensional and the estimate is unique up to phase. This also settles the tie question: no admissible data in D produce a tie.

Measurability. Only measurability and the bounds of w, and continuity of t -> P(t), are used; every inequality above is pointwise in t and then integrated. Nonplanar (for example helical) paths and asymmetric weights are covered, because the bound of Lemma 3.2 is a supremum over all paths with dist(n(t), n0) <= Omega |t| and all weights, which is larger than the admissible class.

## 5. Proof of the theorem, part 2 (lower bound, step (iv))

Fix orthonormal a, e in V and, for a real angle path theta(t), set n(t) = a cos theta(t) + e sin theta(t). Then |<n(t), n(s)>| = |cos(theta(t) - theta(s))|, so dist(n(t), n(s)) <= |theta(t) - theta(s)|, and

  P = aa* cos^2 theta + ee* sin^2 theta + (ae* + ea*) sin theta cos theta,

so M is an affine function of m = int w e^{2 i theta} / int w alone. Take beta = 2 delta(b, R) and
- configuration I: theta1(t) = Omega |t|, w(t) = R where 2 Omega |t| > beta and 1 elsewhere;
- configuration II: theta2(t) = beta - Omega |t|, the same w.

Both are admissible. For I, Im(e^{-i beta} int w e^{2 i theta1}) = int w sin(2 Omega |t| - beta) dt = Phi(beta)/Omega = 0, and Re(e^{-i beta} int w e^{2 i theta1}) = int w cos(2 Omega |t| - beta) > 0 because |2 Omega |t| - beta| <= max(beta, b - beta) < pi/2. So m1 = |m1| e^{i beta}. For II, m2 = e^{2 i beta} conj(m1) = m1. The two configurations give the same M, and their centers a and a cos beta + e sin beta are at distance beta = 2 delta. An estimator that is a function of M returns one ray for both, and by the triangle inequality for dist it is at distance >= delta from one of the centers. In configuration I the principal eigenvector has error exactly delta, so the bound of part 1 is attained. QED.

## 6. Corollary B (SO(3))

Unit quaternions q map onto SO(3) by q -> Rot(q), with Rot(q) = Rot(-q), so SO(3) = RP^3. For unit quaternions p, q, the rotation angle of Rot(p)^T Rot(q) is 2 arccos |p . q| = 2 dist(p, q), and tr(Rot(x)^T Rot(q)) = 1 + 2 cos(2 arccos|x . q|) = 4 (x . q)^2 - 1. Hence:
- a rotation path with rotation-angle Lipschitz constant Omega is a line field in RP^3 with Lipschitz constant Omega/2 (and every such line field lifts to a continuous quaternion path, since t -> P(t) is continuous and RP^3 has the path-lifting property);
- tr(Q^T int w Rot) = int w (4 (x . q(t))^2 - 1) for Q = Rot(x), so the chordal mean is Rot(v) for v the principal eigenvector of M = int w q q^T / int w (Davenport's q-method);
- the 3x3 matrix B = int w Rot / int w and the 4x4 matrix M determine each other by an affine bijection: Rot(q) is a homogeneous quadratic in q, so B = Lin(M) for a linear map Lin on symmetric 4x4 matrices; Lin has rank 9 with kernel spanned by I (Lin(I) = Rot(1) + Rot(i) + Rot(j) + Rot(k) = 0; rank checked numerically by polarization), so it is injective on the trace-one slice where M lives. Estimators that see B are the same as estimators that see M.

Apply the theorem with K = R, d = 4 and b = (Omega/2) L. The quaternion error dist(v, q(0)) <= delta(Omega L/2, R) becomes rotation-angle error <= 2 delta(Omega L/2, R), unique estimate, and the planar lower-bound pair (rotations about one fixed axis) gives the same B with centers 4 delta apart in rotation angle. The condition (Omega L/2, R) in D holds for all R when Omega L <= pi.

## 7. Corollary C

Part 1 and part 2 were written for K = C and H directly: rephasing uses a unit scalar on the right, every great circle used has real coefficients, and h(chi) is computed with real cos chi, sin chi. For CP^1 the map psi -> Bloch vector r with P = (I + r . sigma)/2 sends Fubini-Study distance theta to Bloch angle 2 theta and the principal eigenvector of M to the direction of the weighted mean Bloch vector, which gives the qubit statement.

Remark (spheres, not fully written). The same three steps prove the analogous statement for S^k with the extrinsic mean direction int w x / |int w x|: the error is at most 2 delta(Omega_S L/2, R) for great-circle speed Omega_S. The argument is the linear version of Lemma 3.2 with the support direction at angle pi/2 + chi from x0. It was checked only on paper and is not part of the claim.

## 8. Is b <= pi/2 the right domain?

No. Neither the 2D theorem nor its extension needs b <= pi/2. Where the sketch used b <= pi/2 (the pointwise gap cos 2 rho > 0 and the absence of saturation in the pointwise maximum), the proof above uses only membership in D, which is the condition Phi(pi/2) < 0, equivalently delta(b, R) < pi/4. So in every d and for K = R, C, H, the formula is exact on D = { b < pi, sqrt(R)(sin(b/2) - cos(b/2)) < 1 }, which contains b <= pi/2 for all R; for b in [pi/2, pi) the condition reads R (1 - sin b) < 1 (for example b < 5 pi/6 when R = 2, every b < pi when R = 1).

Outside D the formula fails, in every d including d = 2, so D is sharp. Counterexample (the Z path): theta(t) = Omega t on all of [-L/2, L/2] (the two halves turn in opposite directions), w = R where 2 Omega |t| > pi/2 and 1 elsewhere. Then Im m = 0 by symmetry and Re m is proportional to 1 + R (sin b - 1), which is negative exactly when R (1 - sin b) > 1, that is when (b, R) is strictly outside D (for b in [pi/2, pi)). With m real and negative the principal eigenvector is orthogonal to n0: error pi/2, the largest possible, while delta(b, R) < pi/2. Checked at (b, R) = (2.0, 12), (2.0, 20), (2.5, 4), (2.9, 50), (3.5, 4), (4.0, 2): Re m = -0.09, -0.81, -0.61, -37.0, -4.40, -2.51 (unnormalized), so the error is pi/2 at all six, against delta = 0.793, 0.834, 0.861, 1.313, 1.255, 1.261. This is the mechanism the gap of Corollary 3.3 rules out inside D. Note: the random search found this configuration only at (2.9, 50) and (3.1, 100); at the other outside points it stopped at the V-shaped local optimum with value delta. The search is therefore a weak test of sharpness, and the counterexample was found by hand.

Open points, stated plainly:
- Outside D the principal eigenvector can fail completely (error pi/2); the minimax value over all estimators outside D is not computed.
- The minimax statement is over estimators that see only M (or only B for SO(3)). Estimators with more information are not covered, by design.
- On the boundary of D (delta = pi/4 exactly) the upper bound argument fails at Corollary 3.3 (A >= B only); the boundary case is not checked.

## 9. Numerical checks

Discrete class: on each side of t = 0, 8 cells with free durations; on each cell the unit vector moves at constant speed along a great-circle arc of free direction with arc length <= Omega times the duration, and the weight is a constant in [1, R]. This class is a subset of the admissible class. For the real and the K = C, H line fields, M is computed with the closed form of the cell integral of n n^T over a great-circle arc (exact). For SO(3), B = int w Rot dt is computed from the rotation matrices with 12-point Gauss-Legendre per cell (smooth integrand, error far below the digits shown), the estimate is the SVD projection of B onto SO(3) (not the quaternion route), and the error is the rotation angle. Optimizer: L-BFGS-B with finite differences, random restarts, plus one seed at the planar extremal configuration. "random only" is the best from random restarts alone.

| case | bound | best found | ratio | random starts only |
| --- | --- | --- | --- | --- |
| RP^2 (d=3), b=0.3, R=1 | 0.0750000 | 0.0750000 | 0.9999999 | 0.9999999 |
| RP^2, b=0.3, R=10 | 0.1140154 | 0.1140152 | 0.9999982 | 0.9999982 |
| RP^2, b=0.8, R=30 | 0.3392121 | 0.3392120 | 0.9999997 | 0.9999997 |
| RP^2, b=1.2, R=4 | 0.4027490 | 0.4027487 | 0.9999993 | 0.9999969 |
| RP^2, b=pi/2, R=9 | 0.5969186 | 0.5969186 | 0.9999999 | 0.9999997 |
| RP^2, b=pi/2, R=100 | 0.7194530 | 0.7194529 | 0.9999998 | 0.9999998 |
| RP^3 (d=4), b=0.3, R=1 | 0.0750000 | 0.0749996 | 0.9999947 | 0.9999947 |
| RP^3, b=0.8, R=2 | 0.2347655 | 0.2347654 | 0.9999996 | 0.9999996 |
| RP^3, b=pi/2, R=9 | 0.5969186 | 0.5969186 | 0.9999999 | 0.9999997 |
| RP^2, b=2.0, R=2 (D, b > pi/2) | 0.5934576 | 0.5934576 | 0.9999999 | 0.9999997 |
| RP^2, b=2.0, R=4 (D) | 0.6801271 | 0.6801271 | 1.0000000 | 0.9999999 |
| RP^2, b=2.6, R=1.5 (D) | 0.7266458 | 0.7266457 | 0.9999998 | 0.9999998 |
| RP^2, b=2.5, R=1 (D) | 0.6250000 | 0.6250000 | 1.0000000 | 0.9999968 |
| CP^2, b=0.8, R=5 | 0.2772742 | 0.2772740 | 0.9999994 | same |
| CP^2, b=pi/2, R=3 | 0.5032349 | 0.5032334 | 0.9999971 | same |
| CP^2, b=2.0, R=4 (D) | 0.6801271 | 0.6801266 | 0.9999993 | same |
| HP^1, b=0.8, R=5 | 0.2772742 | 0.2772715 | 0.9999905 | same |
| HP^1, b=pi/2, R=3 | 0.5032349 | 0.5032344 | 0.9999991 | same |
| HP^1, b=2.0, R=4 (D) | 0.6801271 | 0.6223839 | 0.9150995 | same (search did not converge) |
| SO(3), Omega L=0.6, R=3 (rotation angle) | 0.1902625 | 0.1902622 | 0.9999985 | 0.9999985 |
| SO(3), Omega L=1.6, R=1 | 0.4000000 | 0.3999999 | 0.9999996 | 0.9999996 |
| SO(3), Omega L=1.6, R=10 | 0.6098398 | 0.6098396 | 0.9999995 | 0.9999995 |
| SO(3), Omega L=2.4, R=5 | 0.8352213 | 0.8352212 | 0.9999999 | 0.9999999 |
| SO(3), Omega L=pi, R=2 | 0.9272952 | 0.9272951 | 0.9999999 | 0.9999999 |
| SO(3), Omega L=pi, R=50 | 1.3894766 | 1.3894765 | 0.9999999 | 0.9999999 |
| RP^2, b=2.9, R=50 (outside D) | 1.3128285 | 1.5707963 | 1.196 | 1.196 (formula fails) |
| RP^2, b=3.1, R=100 (outside D) | 1.4505582 | 1.5707963 | 1.083 | 1.083 (formula fails) |

No case inside D exceeded the bound (largest ratio 1.0000000 to 7 digits, consistent with attainment by the planar V configuration). The best configurations inside D are planar to optimizer precision (smallest to largest singular value of the cell endpoints at most 8e-5). The CP and HP rows use random starts only, with no planar seed. Points checked outside D are listed in section 8.
