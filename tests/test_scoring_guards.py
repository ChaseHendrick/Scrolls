"""Guards on the scoring tools: checks that could pass without being able to fail.

verify: a control of another shape, or NaN in a map, must not turn into a pass.
auc: NaN or inf is refused, float maps with negative values or a tiny range keep their ranks,
and the map cannot be its own control. ensemble: a NaN weight is refused. gate: a seed 42
mismatch blocks the verdict, and a committed bar replaced by a local result is named.
"""

import json
import tempfile
import unittest
from pathlib import Path

from kit import auc, ensemble, gate, verify

try:
    import numpy as np
    import tifffile
    import zarr
except ImportError:  # the core kit is standard library only
    np = tifffile = zarr = None


def _rank_auc(pred, ink, mask):
    a = pred[mask & ink].ravel().astype(np.float64)
    b = pred[mask & ~ink].ravel().astype(np.float64)
    allv = np.concatenate([a, b])
    order = allv.argsort(kind="stable")
    ranks = np.empty(allv.size)
    ranks[order] = np.arange(1, allv.size + 1)
    _, inv = np.unique(allv, return_inverse=True)
    ranks = (np.bincount(inv, ranks) / np.bincount(inv))[inv]
    return (ranks[:a.size].sum() - a.size * (a.size + 1) / 2) / (a.size * b.size)


@unittest.skipIf(np is None, "numpy is needed")
class VerifyGuardsTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.ref = rng.integers(0, 256, (64, 64)).astype(np.uint8)

    def test_control_of_another_shape_is_an_error_not_a_pass(self):
        with self.assertRaises(verify.VerifyError):
            verify.verify_arrays(self.ref, self.ref.copy(), self.ref[:-1])

    def test_nan_candidate_does_not_agree(self):
        cand = np.full(self.ref.shape, np.nan, np.float32)
        r = verify.verify_arrays(self.ref, cand, 255 - self.ref)
        self.assertEqual(r["verdict"], verify.FAIL)
        self.assertEqual(r["candidate"]["pixels_over_tolerance"], self.ref.size)
        self.assertEqual(r["candidate"]["max_abs_diff"], float("inf"))

    def test_nan_in_both_maps_at_the_same_pixels_agrees(self):
        a = self.ref.astype(np.float32)
        a[0, 0] = np.nan
        r = verify.verify_arrays(a, a.copy(), 255 - self.ref)
        self.assertEqual(r["verdict"], verify.PASS)


@unittest.skipIf(zarr is None, "numpy, tifffile and zarr are needed for kit auc")
class AucGuardsTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.ink = np.zeros((120, 120), bool)
        self.ink[30:90, 30:90] = True
        self.mask = np.ones_like(self.ink)
        self.base = (rng.random(self.ink.shape) * 0.5 + 0.25 + 0.2 * self.ink).astype(np.float32)
        self.want = round(_rank_auc(self.base, self.ink, self.mask), 4)

    def score(self, m):
        return auc.score_array(m, self.ink, self.mask)["auc"]

    def test_tiny_range_negative_and_logit_maps_keep_their_ranks(self):
        self.assertEqual(self.score(self.base), self.want)
        self.assertEqual(self.score(self.base * 1e-6), self.want)
        self.assertEqual(self.score((self.base - 0.5) * 10), self.want)
        self.assertEqual(self.score(-self.base), round(1 - self.want, 4))
        i16 = ((self.base - 0.5) * 10000).astype(np.int16)
        self.assertEqual(self.score(i16), round(_rank_auc(i16, self.ink, self.mask & (i16 != 0)), 4))

    def test_maps_already_on_a_known_scale_quantize_as_before(self):
        u8 = (self.base * 255).astype(np.uint8)
        q, _ = auc._quantize(np, u8)
        self.assertTrue((q == u8).all())
        q, _ = auc._quantize(np, self.base)
        self.assertTrue((q == np.clip(np.round(self.base.astype(np.float64) * 65535), 0, 65535)).all())
        f255 = u8.astype(np.float32)
        q, _ = auc._quantize(np, f255)
        self.assertTrue((q == np.round(f255.astype(np.float64) / 255 * 65535)).all())

    def test_nan_and_inf_are_refused(self):
        for bad in (np.nan, np.inf, -np.inf):
            m = self.base.copy()
            m[0, 0] = bad
            with self.assertRaises(verify.VerifyError):
                self.score(m)

    def test_the_map_is_not_its_own_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            u8 = (self.base * 255).astype(np.uint8)
            tifffile.imwrite(root / "map.tif", u8)
            tifffile.imwrite(root / "copy.tif", u8)
            tifffile.imwrite(root / "rev.tif", u8[::-1].copy())
            for name, a in (("lab.zarr", self.ink), ("msk.zarr", self.mask)):
                g = zarr.open_group(str(root / name), mode="w")
                g.create_array("2", shape=a.shape, dtype="uint8", chunks=(64, 64))[:] = a.astype(np.uint8)
            args = (root / "map.tif", root / "lab.zarr", root / "msk.zarr")
            for ctrl in ("map.tif", "copy.tif"):
                with self.assertRaises(verify.VerifyError):
                    auc.score_files(*args, control=root / ctrl)
            self.assertIn("control", auc.score_files(*args, control=root / "rev.tif"))


@unittest.skipIf(np is None, "numpy is needed")
class EnsembleWeightTest(unittest.TestCase):
    def test_nan_and_inf_weights_are_refused(self):
        maps = [np.full((4, 4), 100, np.uint8), np.full((4, 4), 200, np.uint8)]
        for w in ([float("nan"), 1.0], [float("inf"), 1.0]):
            with self.assertRaises(verify.VerifyError):
                ensemble.combine(maps, "mean", w)


CROPS = {"0841-w00": [0, 640, 0, 640], "0841-ag896": [10, 650, 0, 640], "0841-ag405": [20, 660, 0, 640]}


class GateGuardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        rows = []
        for reader, fwds in (("d9v2", (0.90, 0.82, 0.83)), ("ink_9um seed42", (0.81, 0.66, 0.78))):
            rows += [{"segment": s, "window": "crop", "inner_px": 64, "reader": reader, "auc_as_stored": f,
                      "auc_reversed": 0.55} for s, f in zip(gate.SEGMENTS, fwds)]
        self.results = root / "results.json"
        self.results.write_text(json.dumps({"segments": {s: {"crop": c} for s, c in CROPS.items()}, "results": rows}))
        self.work = root / "work"
        for seg in gate.SEGMENTS:
            (self.work / seg / "results").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, seg, name, fwd, rev=0.5, ctrl_inner=64):
        data = {"forward": {"auc": fwd, "inner": 64}, "control": {"auc": rev, "inner": ctrl_inner}, "crop": CROPS[seg]}
        (self.work / seg / "results" / f"auc_{name}.json").write_text(json.dumps(data))

    def test_seed42_mismatch_blocks_the_verdict(self):
        self.put("0841-w00", "ink9um_s42", 0.7)
        r = gate.run(self.work, self.results)
        self.assertIsNone(r["verdict"]["winner"])
        self.assertFalse(r["verdict"]["clear"])
        self.assertIn("blocked", gate.format_result(r))

    def test_replaced_committed_bar_is_named(self):
        self.put("0841-ag896", "d9v2", 0.99)
        r = gate.run(self.work, self.results)
        self.assertEqual([(x["reader"], x["segment"]) for x in r["replaced"]], [("d9v2", "0841-ag896")])
        self.assertIn("replaced committed bar: d9v2 on 0841-ag896, results.json 0.8200", gate.format_result(r))

    def test_control_scored_with_another_edge_is_skipped(self):
        for seg in gate.SEGMENTS:
            self.put(seg, "v8in", 0.95, ctrl_inner=0)
        r = gate.run(self.work, self.results)
        self.assertNotIn("v8in", [x["reader"] for x in r["ranked"]])
        self.assertTrue(any("control scored" in s for s in r["skipped"]))


if __name__ == "__main__":
    unittest.main()
