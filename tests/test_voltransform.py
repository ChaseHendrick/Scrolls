import json
import unittest
import warnings

from kit import voltransform as V

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

M_AB = [[0.5, 0.0, 0.0, 10.0], [0.0, 0.5, 0.0, 20.0], [0.0, 0.0, 0.5, 30.0]]


def catalog(with_table=True, legacy=True):
    vols = {"A": {"properties": {"pixel_size_um": 2.4}, "data": [
                {"type": "ome-zarr", "origins": [{"path": "S/volumes/A-masked.zarr/"}]},
                {"type": "ome-zarr-vcd3d", "parameters": {"vc_delta3d_version": "0.3.2"},
                 "origins": [{"path": "S/volumes/A-masked-fast-q1-c64-v0.3.2.vcd3d.zarr/"}]}]},
            "B": {"properties": {"pixel_size_um": 4.8}, "data": []}}
    if legacy:
        vols["A"]["properties"]["transforms"] = [{"to_volume_id": "B", "transformation_matrix": M_AB}]
    sample = {"sample": {"properties": {}, "data": [
        {"type": "volume-transform", "parameters": {"from_volume": "A", "to_volume": "B", "revision": 1},
         "properties": {"bent": False}, "origins": [{"path": "S/transforms/A-to-B-r1/"}]},
        {"type": "volume-transform", "parameters": {"from_volume": "A", "to_volume": "B", "revision": 2},
         "properties": {"bent": True}, "origins": [{"path": "S/transforms/A-to-B-r2/"}]}]},
        "volumes": vols, "segments": {"s1": {"data": [
            {"type": "tifxyz-transformed", "parameters": {"target_volume": "B"},
             "origins": [{"path": "S/segments/s1/mesh/s1-on-B-4.8um.tifxyz/"}],
             "properties": {"superseded_by": {"path": "S/segments/s1/mesh/s1-on-B-4.8um-t2.tifxyz/"}}},
            {"type": "tifxyz-transformed", "parameters": {"target_volume": "B", "transform_revision": "2"},
             "origins": [{"path": "S/segments/s1/mesh/s1-on-B-4.8um-t2.tifxyz/"}], "properties": None}]}}}
    if with_table:
        sample["sample"]["properties"]["volume_transforms"] = [
            {"from_volume_id": "A", "transforms": [{"to_volume_id": "B", "revision": 2, "matrix": M_AB,
                                                    "steps": [{"from_volume_id": "A", "to_volume_id": "B",
                                                               "revision": 2, "inverted": False}]}]},
            {"from_volume_id": "B", "transforms": [{"to_volume_id": "A", "revision": 2, "matrix": None,
                                                    "steps": [{"from_volume_id": "A", "to_volume_id": "B",
                                                               "revision": 2, "inverted": True}]}]}]
    return {"samples": {"S": sample}}


class CatalogTests(unittest.TestCase):
    def test_superseded_entries_are_skipped(self):
        data = catalog()["samples"]["S"]["segments"]["s1"]["data"]
        self.assertTrue(V.is_superseded(data[0]))
        self.assertEqual([d["origins"][0]["path"] for d in V.current(data)], [data[1]["origins"][0]["path"]])
        best = V.pick_current(data, key=lambda d: d["parameters"]["target_volume"])
        self.assertEqual(V.transform_revision(best["B"]), 2)
        self.assertEqual(V.replacement(data[0])["path"], data[1]["origins"][0]["path"])

    def test_path_revision(self):
        self.assertEqual(V.path_revision("x/s1-on-B-4.8um.tifxyz/"), 1)
        self.assertEqual(V.path_revision("x/s1-on-B-4.8um-t2.tifxyz/"), 2)
        self.assertEqual(V.path_revision("sv/2.399um-0.22m-78keV-volume-20251217075048-t2.zarr/"), 2)
        self.assertEqual(V.path_revision("ink/P-2.399um-volume-20251217075048-t2-20260417190342-r.tif"), 2)
        self.assertEqual(V.path_revision("ink/P-2.399um-volume-20251217075048-20260417190342-r.tif"), 1)

    def test_volume_affines_from_table_not_deprecated_list(self):
        s = catalog()["samples"]["S"]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            rows = V.volume_affines(s, "A")
        self.assertEqual([(r["to_volume_id"], r["revision"]) for r in rows], [("B", 2)])
        self.assertEqual(V.volume_affines(s, "B"), [])  # B -> A is an inverted chain, not a fit from B

    def test_volume_affines_legacy_fallback_warns(self):
        s = catalog(with_table=False)["samples"]["S"]
        with self.assertWarns(DeprecationWarning):
            rows = V.volume_affines(s, "A")
        self.assertEqual(rows[0]["to_volume_id"], "B")

    def test_chain_spec_and_latest_revision(self):
        cat = catalog()
        self.assertEqual(V.chain_spec(cat, "S", "B", "A")["steps"][0]["inverted"], True)
        with self.assertRaises(V.TransformError):
            V.chain_spec(cat, "S", "A", "C")
        self.assertEqual(V.latest_revision(cat["samples"]["S"], "B", "A"), 2)

    def test_vcd3d_url(self):
        vol = catalog()["samples"]["S"]["volumes"]["A"]
        self.assertTrue(V.vcd3d_url(vol).endswith("/S/volumes/A-masked-fast-q1-c64-v0.3.2.vcd3d.zarr"))
        self.assertIsNone(V.vcd3d_url(catalog()["samples"]["S"]["volumes"]["B"]))
        self.assertEqual(V.vcd3d_sibling("https://h/P/volumes/X-2.4um-masked.zarr/"),
                         "https://h/P/volumes/X-2.4um-masked-fast-q1-c64-v0.3.2.vcd3d.zarr")
        self.assertIsNone(V.vcd3d_sibling("https://h/P/volumes/X.zarr"))


@unittest.skipIf(np is None, "numpy not installed")
class MovingPointsTests(unittest.TestCase):
    def spline_record(self, control, disp, lam=0.0):
        """Fit a 3-D thin-plate spline (U = -r) to displacements, the way villa volreg does with lam=0."""
        centre = control.mean(0)
        scale = float(np.linalg.norm(control - centre, axis=1).max())
        c = (control - centre) / scale
        n = len(c)
        K = -np.sqrt(((c[:, None] - c[None]) ** 2).sum(-1)) - lam * np.eye(n)
        P = np.hstack([np.ones((n, 1)), c])
        A = np.zeros((n + 4, n + 4))
        A[:n, :n], A[:n, n:], A[n:, :n] = K, P, P.T
        sol = np.linalg.solve(A, np.vstack([disp, np.zeros((4, 3))]))
        return {"model": "thin-plate-spline", "kernel": "-r", "centre": centre.tolist(), "scale": scale,
                "regularisation": lam, "effective_parameters": 3 * n, "control_points": control.tolist(),
                "weights": sol[:n].tolist(), "affine": sol[n:].tolist()}

    def test_spline_interpolates_and_inverse_round_trips(self):
        rng = np.random.default_rng(3)
        moving = rng.uniform(0, 1000, (40, 3))
        M = np.array(M_AB)
        bend = 3.0 * np.sin(moving / 150.0)
        fixed = moving @ M[:, :3].T + M[:, 3] + bend
        rec = {"transformation_matrix": M_AB, "deformation": self.spline_record(moving, bend)}
        back = (moving - (fixed @ V.invert_matrix(M)[:, :3].T + V.invert_matrix(M)[:, 3]))
        rec["deformation"]["inverse"] = self.spline_record(fixed, back)
        t = V.Transform.from_json(json.loads(json.dumps(rec)))
        self.assertTrue(t.bent)
        np.testing.assert_allclose(t.apply(moving), fixed, atol=1e-6)
        np.testing.assert_allclose(t.inverted().apply(fixed), moving, atol=1e-6)

    def test_bent_without_inverse_refuses(self):
        rng = np.random.default_rng(4)
        moving = rng.uniform(0, 100, (10, 3))
        t = V.Transform.from_json({"transformation_matrix": M_AB,
                                   "deformation": self.spline_record(moving, np.ones((10, 3)))})
        with self.assertRaises(V.TransformError):
            t.inverted()

    def test_load_chain_uses_table_revision_and_inverts(self):
        files = {V.transform_url("S", "A", "B", 1): {"transformation_matrix": M_AB},
                 V.transform_url("S", "A", "B", 2): {"transformation_matrix": [[0.5, 0, 0, 11.0], [0, 0.5, 0, 20.0],
                                                                                [0, 0, 0.5, 30.0]]}}
        fetch = files.__getitem__
        cat = catalog()
        p = np.array([[100.0, 200.0, 300.0]])
        np.testing.assert_allclose(V.load_chain(cat, "S", "A", "B", fetch).apply(p), [[61.0, 120.0, 180.0]])
        np.testing.assert_allclose(V.load_chain(cat, "S", "A", "B", fetch, revision=1).apply(p), [[60, 120, 180]])
        np.testing.assert_allclose(V.load_chain(cat, "S", "B", "A", fetch).apply([[61.0, 120.0, 180.0]]), p)
        cmp = V.compare_revisions(cat, "S", "A", "B", p, fetch)
        self.assertAlmostEqual(cmp["max"], 1.0)


if __name__ == "__main__":
    unittest.main()
