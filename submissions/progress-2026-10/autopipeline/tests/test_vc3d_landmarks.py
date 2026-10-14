"""Checks of cross-scan transforms against their landmarks and the CT (kit/vc3d_landmarks.py, kit/vc3d_region.py).

Synthetic transforms with known errors: a matrix that was not fitted to its landmarks, a misplaced landmark,
four landmarks (an exact fit), flat sets, a mirror, a scale off the voxel sizes. The image check runs on
synthetic volumes whose true transform is known, with a matrix shifted by a known amount, through a local
S3-like server that answers false 404s.
"""

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import vc3d_agent, vc3d_catalog, vc3d_landmarks as L  # noqa: E402

HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
INV = L.INVERSE


def rotation(axis, deg):
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
            [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
            [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]]


def similarity(scale, deg=30.0, axis=(1, 2, 3), t=(100.0, -50.0, 20.0), mirror=False):
    r = rotation(axis, deg)
    f = -1.0 if mirror else 1.0
    return [[scale * r[i][0] * f, scale * r[i][1], scale * r[i][2], t[i]] for i in range(3)]


def spread_points(n, lo=0.0, hi=4000.0, flat=None, seed=3):
    """n points spread through a box (or nearly flat in z when flat is a thickness)."""
    import random
    rng = random.Random(seed)
    pts = []
    for _ in range(n):
        z = rng.uniform(2000, 2000 + flat) if flat is not None else rng.uniform(lo, hi)
        pts.append((rng.uniform(lo, hi), rng.uniform(lo, hi), z))
    return pts


def noisy(points, sd, seed=5):
    import random
    rng = random.Random(seed)
    return [tuple(v + rng.gauss(0, sd) for v in p) for p in points]


def transform(m, src, to="T", noise=0.0, seed=5):
    """A stored transform as the catalog has them: landmarks from m (plus noise), and the matrix their
    least-squares affine fit (m itself when they do not fix one)."""
    dst = [L.apply(m, p) for p in src]
    if noise:
        dst = noisy(dst, noise, seed)
    fit = L.fit_affine(src, dst)
    return {"to_volume_id": to, "transformation_matrix": fit or m, "from_landmarks": [list(p) for p in src],
            "to_landmarks": [list(p) for p in dst]}


class TestAlgebra(unittest.TestCase):
    def test_invert_compose_decompose(self):
        m = similarity(0.4706, deg=40, mirror=True)
        ident = L.compose(L.invert(m), m)
        for i in range(3):
            for j in range(4):
                self.assertAlmostEqual(ident[i][j], float(i == j), places=9)
        d = L.decompose(m)
        self.assertTrue(d["mirror"])
        self.assertAlmostEqual(d["mean_scale"], 0.4706, places=9)
        self.assertLess(d["anisotropy"], 1e-9)
        self.assertAlmostEqual(d["rotation_deg"], 40.0, places=6)
        self.assertAlmostEqual(L.decompose(similarity(2.0, deg=0))["rotation_deg"], 0.0, places=6)
        with self.assertRaises(L.LandmarkError):
            L.invert([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0]])
        vals, vecs = L.eig_sym([[2.0, 1.0, 0.0], [1.0, 2.0, 0.0], [0.0, 0.0, 5.0]])
        self.assertEqual([round(v, 9) for v in vals], [5.0, 3.0, 1.0])
        self.assertAlmostEqual(abs(vecs[0][1]), math.sqrt(0.5), places=9)

    def test_fits_recover_known_transforms(self):
        src = spread_points(9)
        for mirror in (False, True):
            m = similarity(3.9, deg=-75, axis=(0.2, 1, 0.1), mirror=mirror)
            dst = [L.apply(m, p) for p in src]
            for fit in (L.fit_affine(src, dst), L.fit_similarity(src, dst, mirror=mirror)):
                self.assertLess(max(L.residuals(fit, src, dst)), 1e-6)
        aff = [[1.1, 0.2, 0.0, 5.0], [0.1, 0.9, 0.3, -2.0], [0.0, 0.05, 1.3, 7.0]]
        self.assertLess(max(L.residuals(L.fit_affine(src, [L.apply(aff, p) for p in src]), src,
                                        [L.apply(aff, p) for p in src])), 1e-6)
        self.assertIsNone(L.fit_affine(src[:3], src[:3]))                     # three points fix no affine
        plane = [(x, y, 7.0) for x, y, _ in src]
        self.assertIsNone(L.fit_affine(plane, plane))                         # nor do points in one plane
        self.assertIsNone(L.fit_similarity(src[:2], src[:2]))
        self.assertEqual([round(v) for v in L.spread([(0, 0, 0), (10, 0, 0)])], [5, 0, 0])


class TestCheckTransform(unittest.TestCase):
    """One volume at 2.4 um mapped to one at 9.362 um (scale 0.25635), distances in um of the target."""

    FROM, TO = 2.4, 9.362

    def check(self, t, **kw):
        return L.check_transform(t, self.FROM, self.TO, **kw)

    def m(self, **kw):
        return similarity(self.FROM / self.TO, **kw)

    def test_consistent(self):
        rep = self.check(transform(self.m(), spread_points(12), noise=0.5))
        self.assertEqual((rep["verdict"], rep["reason"], rep["flags"]), ("consistent", None, {}))
        self.assertLess(rep["leave_one_out_affine"]["max_um"], 30)
        self.assertLess(rep["affine_refit"]["differs_from_stored_um"], 10)
        self.assertAlmostEqual(rep["matrix"]["scale_vs_voxel_ratio_pct"], 0.0, delta=0.1)

    def test_a_matrix_not_made_from_its_landmarks(self):
        t = transform(self.m(), spread_points(8), noise=0.2)
        t["transformation_matrix"] = [r[:3] + [r[3] + (12.0 if i == 0 else 0.0)] for i, r in
                                      enumerate(t["transformation_matrix"])]          # 12 voxels = 112 um off
        rep = self.check(t)
        self.assertEqual(rep["verdict"], "inconsistent")
        self.assertIn("not made from these landmarks", rep["reason"])
        self.assertAlmostEqual(rep["stored"]["median_um"], 12 * self.TO, delta=5)
        self.assertLess(rep["affine_refit"]["max_um"], 10)

    def test_a_misplaced_landmark(self):
        t = transform(self.m(), spread_points(8), noise=0.2)
        t["to_landmarks"][3][1] += 40.0                                               # 374 um
        rep = self.check(t)
        self.assertEqual(rep["verdict"], "inconsistent")
        self.assertIn("no affine fits", rep["reason"])
        loo = rep["leave_one_out_affine"]["per_landmark"]
        self.assertEqual(loo.index(max(loo)), 3)

    def test_few_and_flat_landmarks(self):
        four = self.check(transform(self.m(), spread_points(4), noise=1.0))
        self.assertEqual(four["verdict"], "weak")
        self.assertIn("fit any affine exactly", four["reason"])
        self.assertLess(four["stored"]["max_um"], 1e-6)
        self.assertIn("leave_one_out_similarity", four)
        flat = self.check(transform(self.m(), spread_points(6, flat=20.0), noise=2.0))
        self.assertEqual(flat["verdict"], "weak")
        self.assertIn("flat", flat["flags"])
        self.assertIn("similarity", flat["flags"])         # the 7-parameter fit holds up where the affine does not
        self.assertIn("mirror", flat["flags"])             # the affine fit even tilted through a mirror
        for n in (0, 3):
            rep = self.check(transform(self.m(), spread_points(n)))
            self.assertEqual(rep["verdict"], "unchecked")
        plane = transform(self.m(), [(x, y, 500.0) for x, y, _ in spread_points(6)])
        self.assertIn("one plane", self.check(plane)["reason"])

    def test_flags(self):
        rep = self.check(transform(self.m(mirror=True), spread_points(10), noise=0.3))
        self.assertTrue(rep["matrix"]["mirror"])
        self.assertIn("mirror", rep["flags"])
        rep = L.check_transform(transform(self.m(), spread_points(10)), self.FROM * 1.03, self.TO)
        self.assertIn("scale", rep["flags"])
        stretched = [[v * (1.05 if i == 0 and j < 3 else 1.0) for j, v in enumerate(r)] for i, r in
                     enumerate(self.m())]
        self.assertIn("anisotropy", self.check(transform(stretched, spread_points(10)))["flags"])
        voxels = L.check_transform(transform(self.m(), spread_points(10)))
        self.assertEqual(voxels["units"], "target voxels")

    def test_error_at_grows_away_from_the_landmarks(self):
        src = spread_points(10, 1000, 2000)
        t = transform(self.m(), src, noise=1.0)
        rep = self.check(t, at=[(1500, 1500, 1500), (20000, 20000, 20000)])["at"]
        near, far = rep["rows"]
        self.assertTrue(near["inside_landmark_box"] and not far["inside_landmark_box"])
        self.assertGreater(far["jackknife_affine_um"], 5 * near["jackknife_affine_um"])
        self.assertGreater(far["nearest_landmark_um"], 40000)
        self.assertEqual(rep["inside_landmark_box_share"], 0.5)


def tiny_catalog(tamper=False, missing_hop=False):
    """Sample S: A (2.4 um) -> B (9.362 um) stored with 10 landmarks, C (1.2 um) -> A with 8, D -> B with
    none; the table holds every pair with its derivation path."""
    mab = similarity(2.4 / 9.362, deg=20)
    mca = similarity(0.5, deg=-10, axis=(0, 0, 1), t=(30.0, 40.0, 50.0), mirror=True)
    mdb = similarity(1.0, deg=0, t=(5.0, 0.0, 0.0))
    stored = {("A", "B"): transform(mab, spread_points(10), to="B", noise=0.3),
              ("C", "A"): transform(mca, spread_points(8, seed=9), to="A", noise=0.2),
              ("D", "B"): {"to_volume_id": "B", "transformation_matrix": mdb}}
    vols = {"A": (2.4, [9000, 8000, 8000]), "B": (9.362, [2300, 2050, 2050]), "C": (1.2, [18000, 16000, 16000]),
            "D": (9.362, [2300, 2050, 2050])}
    paths = {("A", "B"): "A-B", ("B", "A"): f"B-A{INV}", ("C", "A"): "C-A", ("A", "C"): f"A-C{INV}",
             ("C", "B"): "C-A.A-B", ("B", "C"): f"B-A{INV}.A-C{INV}", ("D", "B"): "D-B"}
    if missing_hop:
        paths[("D", "C")] = "D-B.B-C"
    table = {}
    for (a, b), path in paths.items():
        comp = None
        try:
            for x, y, inverted in L.parse_path(path):
                hm = L.invert(stored[(y, x)]["transformation_matrix"]) if inverted else \
                    stored[(x, y)]["transformation_matrix"]
                comp = hm if comp is None else L.compose(hm, comp)
        except KeyError:
            comp = similarity(1.0)
        if tamper and (a, b) == ("C", "B"):
            comp = [r[:3] + [r[3] + 0.5] for r in comp]
        table.setdefault(a, []).append({"to_volume_id": b, "matrix": comp, "derivation_path": path})
    volumes = {}
    for vid, (um, shape) in vols.items():
        props = {"pixel_size_um": um, "shape": shape,
                 "transforms": [t for (a, _), t in stored.items() if a == vid]}
        volumes[vid] = {"properties": props,
                        "data": [{"type": "ome-zarr", "origins": [{"path": f"S/volumes/{vid}.zarr"}]}]}
    return {"samples": {"S": {"sample": {"properties": {"volume_transforms": [
        {"from_volume_id": a, "transforms": ts} for a, ts in table.items()]}}, "volumes": volumes}}}


class TestCatalog(unittest.TestCase):
    def test_check_catalog_and_the_derived_table(self):
        rep = L.check_catalog(tiny_catalog())
        self.assertEqual(rep["counts"], {"inconsistent": 0, "weak": 0, "consistent": 2, "unchecked": 1})
        self.assertEqual(rep["mirrored"], ["S C to A"])
        self.assertEqual((rep["derived"]["S"]["entries"], rep["derived"]["S"]["problems"]), (7, []))
        bad = L.derived_table(tiny_catalog(tamper=True), "S")
        wrong = [r for r in bad if not r["ok"]]
        self.assertEqual([(r["from"], r["to"]) for r in wrong], [("C", "B")])
        self.assertAlmostEqual(wrong[0]["max_difference_um"], 0.5 * 9.362 * math.sqrt(3), places=3)
        broken = [r for r in L.derived_table(tiny_catalog(missing_hop=True), "S") if not r["ok"]]
        self.assertIn("no volume stores", broken[0]["problem"])
        self.assertEqual(L.parse_path(f"A-B{INV}.B-C"), [("A", "B", True), ("B", "C", False)])
        with self.assertRaises(L.LandmarkError):
            L.parse_path("AB")
        self.assertEqual(len(L.check_catalog(tiny_catalog(), "S", from_volume="C")["transforms"]), 1)
        with self.assertRaises(L.LandmarkError):
            L.check_catalog(tiny_catalog(), "S", from_volume="Z")

    def test_shared_landmarks_are_noted(self):
        cat = tiny_catalog()
        vols = cat["samples"]["S"]["volumes"]
        twin = json.loads(json.dumps(vols["A"]["properties"]["transforms"][0]))
        vols["D"]["properties"]["transforms"] = [twin]
        rows = {(r["from"], r["to"]): r for r in L.check_catalog(cat)["transforms"]}
        self.assertEqual(rows[("D", "B")]["same_landmarks_as"], ["S A to B"])

    def test_error_along_a_chained_path(self):
        cat = tiny_catalog()
        pts = [(4000.0, 4000.0, 4000.0), (100.0, 100.0, 100.0)]
        rep = L.error_along(cat, "S", "B", "C", pts)
        self.assertEqual(rep["path"], f"B-A{INV}.A-C{INV}")
        self.assertEqual([h["inverted"] for h in rep["hops"]], [True, True])
        stored = {(vid, t["to_volume_id"]): t["transformation_matrix"] for _, vid, t in L.stored_transforms(cat, "S")}
        direct = L.compose(L.invert(stored[("C", "A")]), L.invert(stored[("A", "B")]))
        for row, p in zip(rep["rows"], pts):
            self.assertLess(math.dist(row["mapped"], L.apply(direct, p)), 0.02)
        first = rep["rows"][0]["jackknife_affine_um"]
        hop1 = rep["hops"][0]["jackknife_affine_max_um"]
        self.assertGreaterEqual(first + 1e-6, 0)
        self.assertGreaterEqual(rep["jackknife_affine_max_um"] + 1e-6, hop1)
        self.assertEqual(rep["rows"][1]["inside_target_volume"], True)
        none = L.error_along(cat, "S", "D", "B", pts)
        self.assertIsNone(none["rows"][0]["jackknife_affine_um"])
        with self.assertRaises(L.LandmarkError):
            L.error_along(cat, "S", "A", "D", pts)


class TestTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.home = self.d / "home"
        (self.home / "cache").mkdir(parents=True)
        (self.home / "cache" / "open-data-metadata.json").write_text(json.dumps(tiny_catalog()))
        self.ctx = vc3d_agent.Context(env=fakes.env_for(self.d / "bin", self.home))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, args):
        return vc3d_agent.call("landmarks", args, self.ctx)

    def test_catalog_check_and_at(self):
        res = self.call({})
        self.assertEqual(res["counts"]["consistent"], 2)
        self.assertEqual({r["from"] for r in res["transforms"]}, {"A", "C", "D"})
        full = json.loads(Path(res["report"]).read_text())
        self.assertIn("leave_one_out_affine", full["transforms"][0])
        self.assertTrue(Path(res["receipt"]).is_file())
        at = self.call({"from_volume": "S/volumes/B.zarr", "to_volume": "C", "at": [[100, 100, 100]]})
        self.assertEqual((at["sample"], at["path"], at["points"]), ("S", f"B-A{INV}.A-C{INV}", 1))
        surf = fakes.write_tifxyz(self.d / "s.tifxyz", lambda r, c: (1000.0 + 10 * c, 1000.0 + 10 * r, 900.0))
        on = self.call({"from_volume": "A", "to_volume": "B", "surface": str(surf), "tolerance_um": 0.1})
        self.assertEqual(on["points"], 81)
        self.assertIn("warning", on)
        for bad in ({"at": [[1, 2, 3]]}, {"from_volume": "Q"},
                    {"from_volume": "A", "to_volume": "D", "at": [[1, 2, 3]]}):
            with self.subTest(bad=bad), self.assertRaises(vc3d_agent.ToolError):
                self.call(bad)


@unittest.skipUnless(HAVE_NUMPY, "the image check needs numpy")
class TestRegionAndImage(unittest.TestCase):
    """A smooth random texture at 1 um (the fine scan) and the same texture seen through a known similarity
    at 2 um (the coarse scan)."""

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        rng = np.random.default_rng(7)
        n = 128
        k = np.fft.fftfreq(n)
        g = np.exp(-2 * (np.pi * 2.5) ** 2 * (k[:, None, None] ** 2 + k[None, :, None] ** 2 + k[None, None, :] ** 2))
        a = np.real(np.fft.ifftn(np.fft.fftn(rng.normal(size=(n, n, n))) * g))
        fine = ((a - a.min()) / (a.max() - a.min()) * 200 + 30).astype(np.uint8)
        cls.fine = fine
        cls.m = similarity(0.5, deg=12, axis=(0.3, 0.2, 1.0), t=(4.0, 2.0, 3.0))      # fine (from) -> coarse (to)
        inv = np.array(L.invert(cls.m))
        q = np.indices((64, 64, 64)).reshape(3, -1).T[:, ::-1].astype(float)     # x, y, z of every coarse voxel
        p = q @ inv[:, :3].T + inv[:, 3]
        cls.coarse = cls.trilinear(fine.astype(float), p).reshape(64, 64, 64).round().astype(np.uint8)
        # points whose neighbourhoods lie inside both volumes and far from each other's
        cls.POINTS = [L.apply(L.invert(cls.m), q) for q in ((18, 18, 18), (46, 46, 18), (46, 18, 46), (18, 46, 46))]
        write_zarr(cls.d / "fine.zarr", fine)
        write_zarr(cls.d / "coarse.zarr", cls.coarse)
        write_zarr(cls.d / "blank.zarr", np.zeros((64, 64, 64), np.uint8))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def trilinear(cls, a, xyz):
        np = cls.np
        zyx = xyz[:, ::-1]
        i0 = np.floor(zyx).astype(int)
        f = zyx - i0
        out = np.zeros(len(zyx))
        for dz in (0, 1):
            for dy in (0, 1):
                for dx in (0, 1):
                    w = ((f[:, 0] if dz else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) *
                         (f[:, 2] if dx else 1 - f[:, 2]))
                    iz, iy, ix = i0[:, 0] + dz, i0[:, 1] + dy, i0[:, 2] + dx
                    ok = (iz >= 0) & (iz < a.shape[0]) & (iy >= 0) & (iy < a.shape[1]) & (ix >= 0) & (ix < a.shape[2])
                    out[ok] += w[ok] * a[iz[ok], iy[ok], ix[ok]]
        return out

    def vol(self, name, um):
        from kit import vc3d_region
        return vc3d_region.Volume(self.d / name, voxel_um=um)

    OPT = {"patch": 16, "search": 6, "exclude": 2.0}

    def test_region_reads_and_samples(self):
        from kit import vc3d_region
        np = self.np
        v = self.vol("fine.zarr", 1.0)
        box = v.read(0, [[-3, 40], [30, 70], [100, 140]])
        self.assertTrue(np.array_equal(box[3:, :, :28], self.fine[0:40, 30:70, 100:128]))
        self.assertTrue((box[:3] == 0).all() and (box[:, :, 28:] == 0).all())
        ramp = np.fromfunction(lambda z, y, x: x + 2 * y + 3 * z, (16, 16, 16)).astype(np.uint8)
        write_zarr(self.d / "ramp.zarr", ramp, chunk=8)
        r = vc3d_region.Volume(self.d / "ramp.zarr")
        self.assertAlmostEqual(float(r.sample(0, [[1.5, 2.25, 3.75]])[0]), 1.5 + 4.5 + 11.25, places=9)
        (self.d / "ramp.zarr" / "0" / "1" / "1" / "1").unlink()
        self.assertEqual(int(r.read(0, [[8, 16], [8, 16], [8, 16]]).sum()), 0)
        self.assertEqual(r.missing, 1)
        t = self.fine[10:26, 20:36, 30:46].astype(float)
        ncc = vc3d_region.ncc_map(t, self.fine[5:35, 15:45, 25:55].astype(float))
        best, pos, side = vc3d_region.peak(ncc, 2.0)
        self.assertAlmostEqual(best, 1.0, places=6)
        self.assertEqual([round(v) for v in pos], [5, 5, 5])
        self.assertLess(side, 0.9)
        self.assertIsNone(vc3d_region.ncc_map(np.ones((4, 4, 4)), self.fine[:8, :8, :8]))

    def test_the_true_matrix_matches(self):
        rep = L.image_check(self.m, self.vol("fine.zarr", 1.0), self.vol("coarse.zarr", 2.0), self.POINTS, 1.0, 2.0,
                            to_points=[L.apply(self.m, p) for p in self.POINTS], tolerance_um=3.0, **self.OPT)
        self.assertEqual(rep["counts"], {"matches": 4})
        self.assertTrue(all(r["offset_norm_um"] < 1.0 for r in rep["rows"]))
        self.assertTrue(rep["control"]["passed"])
        self.assertEqual(rep["setup"]["coarse"], "to")
        self.assertLess(rep["landmark_error_um"]["max"], 1.0)

    def test_a_shifted_matrix_is_caught_and_the_landmarks_vindicated(self):
        shifted = [r[:3] + [r[3] + (3.0 if i == 0 else 0.0)] for i, r in enumerate(self.m)]   # 3 voxels, 6 um in x
        true_to = [L.apply(self.m, p) for p in self.POINTS]
        rep = L.image_check(shifted, self.vol("fine.zarr", 1.0), self.vol("coarse.zarr", 2.0), self.POINTS, 1.0, 2.0,
                            to_points=true_to, tolerance_um=3.0, **self.OPT)
        self.assertEqual(rep["counts"], {"offset": 4})
        for r in rep["rows"]:
            self.assertAlmostEqual(r["offset_um"][0], -6.0, delta=0.8)
            self.assertLess(abs(r["offset_um"][1]) + abs(r["offset_um"][2]), 1.6)
            self.assertAlmostEqual(r["landmark_residual_um"], 6.0, delta=0.01)
            self.assertLess(r["landmark_error_um"], 1.0)                 # the CT agrees with the landmarks

    def test_from_the_coarse_scan(self):
        inv = L.invert(self.m)                                            # coarse (from) -> fine (to)
        shifted = [r[:3] + [r[3] + (2.0 if i == 1 else 0.0)] for i, r in enumerate(inv)]   # 2 um in y
        pts = [L.apply(self.m, p) for p in self.POINTS]
        rep = L.image_check(shifted, self.vol("coarse.zarr", 2.0), self.vol("fine.zarr", 1.0), pts, 2.0, 1.0,
                            tolerance_um=1.0, **self.OPT)
        self.assertEqual(rep["setup"]["coarse"], "from")
        for r in rep["rows"]:
            self.assertEqual(r["verdict"], "offset")
            self.assertAlmostEqual(r["offset_um"][1], -2.0, delta=0.8)

    def test_no_structure_and_a_remote_volume(self):
        rep = L.image_check(self.m, self.vol("fine.zarr", 1.0), self.vol("blank.zarr", 2.0), self.POINTS[:3], 1.0,
                            2.0, **self.OPT)
        self.assertEqual(rep["counts"], {"no_structure": 3})
        self.assertIsNone(rep["control"]["passed"])
        from kit import vc3d_region
        with fakes.S3LikeServer(self.d, false=1) as srv:
            remote = vc3d_region.Volume(srv.url + "/coarse.zarr", voxel_um=2.0, opener=fakes.no_proxy_opener(),
                                        rate=0)
            rep = L.image_check(self.m, self.vol("fine.zarr", 1.0), remote, self.POINTS, 1.0, 2.0, tolerance_um=3.0,
                                **self.OPT)
            self.assertEqual(rep["counts"], {"matches": 4})
            self.assertGreater(remote.store.false_404s, 0)

    def test_the_tool_runs_the_image_check(self):
        cat = {"samples": {"S": {"sample": {"properties": {"volume_transforms": [
            {"from_volume_id": "F",
             "transforms": [{"to_volume_id": "K", "matrix": self.m, "derivation_path": "F-K"}]}]}},
            "volumes": {
                "F": {"properties": {"pixel_size_um": 1.0, "shape": [128, 128, 128],
                                     "transforms": [transform(self.m, self.POINTS, to="K")]},
                      "data": [{"type": "ome-zarr", "origins": [{"path": "fine.zarr"}]}]},
                "K": {"properties": {"pixel_size_um": 2.0, "shape": [64, 64, 64]},
                      "data": [{"type": "ome-zarr", "origins": [{"path": "coarse.zarr"}]}]}}}}}
        home = self.d / "toolhome"
        (home / "cache").mkdir(parents=True, exist_ok=True)
        (home / "cache" / "open-data-metadata.json").write_text(json.dumps(cat))
        ctx = vc3d_agent.Context(env=fakes.env_for(self.d / "bin", home))
        with fakes.S3LikeServer(self.d, false=0) as srv, mock.patch.object(vc3d_catalog, "BUCKET_URL", srv.url):
            res = vc3d_agent.call("landmarks", {"from_volume": "F", "to_volume": "K", "image": True,
                                                "tolerance_um": 3.0, **self.OPT}, ctx)
            with self.assertRaises(vc3d_agent.ToolError):     # nothing left to compare the peak with
                vc3d_agent.call("landmarks", {"from_volume": "F", "to_volume": "K", "image": True, "search": 6}, ctx)
        lm = res["image_check"]["landmarks"]
        self.assertEqual((lm["counts"], lm["control"]["passed"]), ({"matches": 4}, True))
        self.assertNotIn("rows", lm)
        self.assertEqual(len(json.loads(Path(res["report"]).read_text())["image_check"]["landmarks"]["rows"]), 4)


def write_zarr(path, arr, chunk=32):
    """A one-level OME-Zarr group of a uint8 numpy array, uncompressed, chunks padded to full size."""
    import numpy as np
    p = Path(path)
    (p / "0").mkdir(parents=True, exist_ok=True)
    (p / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (p / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4", "axes": [
        {"name": a, "type": "space"} for a in "zyx"], "datasets": [{"path": "0", "coordinateTransformations": [
            {"type": "scale", "scale": [1.0, 1.0, 1.0]}]}]}]}))
    (p / "0" / ".zarray").write_text(json.dumps({
        "zarr_format": 2, "shape": list(arr.shape), "chunks": [chunk] * 3, "dtype": "|u1", "compressor": None,
        "fill_value": 0, "filters": None, "order": "C", "dimension_separator": "/"}))
    counts = [-(-s // chunk) for s in arr.shape]
    for iz in range(counts[0]):
        for iy in range(counts[1]):
            for ix in range(counts[2]):
                block = np.zeros((chunk,) * 3, np.uint8)
                part = arr[iz * chunk:(iz + 1) * chunk, iy * chunk:(iy + 1) * chunk, ix * chunk:(ix + 1) * chunk]
                block[:part.shape[0], :part.shape[1], :part.shape[2]] = part
                out = p / "0" / str(iz) / str(iy) / str(ix)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(block.tobytes())
    return p


if __name__ == "__main__":
    unittest.main()
