"""kit fibertensor: structure-tensor features find texture-only ink that brightness cannot."""

import unittest

try:
    import numpy as np
    import scipy.ndimage  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

from kit import auc


def phantom(seed, size=160, layers=10, angle=0.3):
    """Fibres at `angle` and angle + 90 deg; ink discs replace fibres by isotropic texture of equal mean and spread."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:size, :size].astype(float)
    u = xx * np.cos(angle) + yy * np.sin(angle)
    v = -xx * np.sin(angle) + yy * np.cos(angle)
    ink = np.zeros((size, size), bool)
    for _ in range(14):
        cy, cx, r = rng.integers(10, size - 10), rng.integers(10, size - 10), rng.integers(5, 10)
        ink |= (yy - cy) ** 2 + (xx - cx) ** 2 < r * r
    vol = np.empty((layers, size, size), np.float32)
    for k in range(layers):
        fib = np.sin(u / 1.6 + k) + 0.6 * np.sin(v / 2.3)
        iso = scipy.ndimage.gaussian_filter(rng.normal(size=(size, size)), 1.2)
        iso = (iso - iso.mean()) / iso.std() * fib.std() + fib.mean()
        img = np.where(ink, iso, fib) + 0.3 * rng.normal(size=(size, size))
        vol[k] = img
    return vol, ink


@unittest.skipIf(np is None, "needs numpy and scipy")
class FibreTensorTest(unittest.TestCase):
    def test_texture_ink_found_and_brightness_fails(self):
        from kit import fibertensor as ft
        vtr, itr = phantom(1)
        vte, ite = phantom(2, angle=0.9)          # held-out phantom, fibres rotated: axis must be re-measured
        sup = np.ones_like(itr)
        res = {}
        for kind in ("fibre", "raw"):
            f, _ = ft.features(vtr, kind)
            p = ft.fit(f, itr, sup, model="logreg", samples=8000, epochs=150)
            g, axes = ft.features(vte, kind)
            m = ft.predict(p, g)
            self.assertTrue(((m > 0) & (m <= 1)).all())
            res[kind] = auc.score_array(m, ite, np.ones_like(ite))["auc"]
        self.assertGreater(res["fibre"], 0.8, res)
        self.assertLess(abs(res["raw"] - 0.5), 0.1, res)

    def test_fibre_axis_recovers_angle(self):
        from kit import fibertensor as ft
        import scipy.ndimage as ndi
        yy, xx = np.mgrid[:128, :128].astype(float)
        a = 0.4
        img = np.sin((xx * np.cos(a) + yy * np.sin(a)) / 2.0)
        ax = ft.fibre_axis(np, ndi, img)
        # gradient points across the stripes, i.e. along angle a (mod pi)
        self.assertAlmostEqual(np.sin(2 * (ax - a)), 0.0, places=2)

    def test_model_roundtrip_and_errors(self):
        import tempfile, os
        from kit import fibertensor as ft
        from kit.verify import VerifyError
        v, i = phantom(3, size=64, layers=6)
        f, _ = ft.features(v, "raw")
        p = ft.fit(f, i, np.ones_like(i), model="mlp", hidden=4, samples=2000, epochs=20)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.npz")
            ft.save_model(path, p, {"kind": "raw", "features": int(f.shape[0])})
            q, meta = ft.load_model(path)
            self.assertEqual(meta["kind"], "raw")
            np.testing.assert_allclose(ft.predict(q, f), ft.predict(p, f))
        with self.assertRaises(VerifyError):
            ft.fit(f, np.zeros_like(i), np.ones_like(i))
        with self.assertRaises(VerifyError):
            ft.features(v[:2], "raw")


if __name__ == "__main__":
    unittest.main()
