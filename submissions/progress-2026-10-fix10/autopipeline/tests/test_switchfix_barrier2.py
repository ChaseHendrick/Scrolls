"""Tests for kit switchfix's barrier version 2 (BARRIER2) on synthetic sheets: no network, no scroll data.

The case version 2 is for: m7 draws two touching sheets as one run over a stretch longer than version 1's zone
dilation, so the two sides of the merge fall in separate zones, each touched from one side, and version 1 lets the
hop through. Controls that can fail: version 2 with version 1's zone setting reproduces version 1 exactly (parity);
a trace that stays on its sheet through the same long merge keeps its far side (no false cut); with no zone marked
the hop is joined (the cut is the barrier's)."""

import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

from kit import switchfix as sf

SHAPE = (112, 216, 740)      # z, y, x; the seed side must exceed the 4 mm2 hole limit (45,640 voxel^2)
ZA = 49.5
M0, M1 = 400, 500            # the merge: one run from x 400 to 500 (100 voxels, wider than 2 x 9 dense cells)
SEED = (12.0, 24.0, ZA)


class ArrayReader:
    def __init__(self, vol, chunk=32):
        self.vol, self.chunks = vol, (chunk,) * 3
        self.meta = {"shape": list(vol.shape)}

    def read(self, key):
        c = self.chunks[0]
        z, y, x = (int(k) * c for k in key)
        out = np.zeros(self.chunks, np.uint8)
        part = self.vol[z:z + c, y:y + c, x:x + c]
        out[:part.shape[0], :part.shape[1], :part.shape[2]] = part
        return out


def sheets(a_of_x, b_of_x):
    v = np.zeros(SHAPE, np.uint8)
    for zc in (a_of_x, b_of_x):
        for x in range(SHAPE[2]):
            c = float(zc(x))
            v[int(round(c - 1.5)):int(round(c + 1.5)) + 1, :, x] = 1
    return v


def long_hop():
    """B comes to 6 voxels above A, the two are one run from M0 to M1, then A lies 6 (later 14) voxels below the
    trace: the trace left the merge on B."""
    return sheets(lambda x: ZA if x < M1 else (ZA - 6 if x < M1 + 30 else ZA - 14),
                  lambda x: ZA + 14 if x < M0 - 30 else (ZA + 6 if x < M0 else ZA))


def long_stay():
    """The same long merge, but B lies above the trace on both sides of it: the trace stayed on A."""
    return sheets(lambda x: ZA, lambda x: ZA if M0 <= x < M1 else (ZA + 6 if M0 - 30 <= x < M1 + 30 else ZA + 14))


def short_hop():
    """Version 1's own case: a merge 28 voxels long (x 436 to 464), the seed's side wider than the hole limit even
    after version 2's wider cut."""
    return sheets(lambda x: ZA if x < 464 else (ZA - 6 if x < 500 else ZA - 14),
                  lambda x: ZA + 14 if x < 400 else (ZA + 6 if x < 436 else ZA))


def short_hop_near_seed():
    """The same merge 100 voxels further left: the seed's side (x below about 180) is under the 4 mm2 hole limit,
    so kit.sheetgap drops it and version 1 keeps the far side, past the hop."""
    return sheets(lambda x: ZA if x < 264 else (ZA - 6 if x < 300 else ZA - 14),
                  lambda x: ZA + 14 if x < 200 else (ZA + 6 if x < 236 else ZA))


def apart():
    return sheets(lambda x: ZA, lambda x: ZA + 14)


def mesh(step=4):
    xs = np.arange(8, SHAPE[2] - 7, step, dtype=float)
    ys = np.arange(8, SHAPE[1] - 7, step, dtype=float)
    X, Y = np.meshgrid(xs, ys)
    return np.stack([X, Y, np.full(X.shape, ZA)], -1), np.ones(X.shape, bool)


def field(vol):
    from kit import sheetgap
    return sheetgap.Field(ArrayReader(vol), 1)


def params(**zone):
    return dict(sf.BARRIER2, zone=zone)


V1_ZONE = {"group_dilate_cells": 9, "mark": "group"}


@unittest.skipIf(np is None, "needs numpy and scipy")
class Barrier2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.xyz, cls.valid = mesh()
        cls.X = cls.xyz[..., 0]
        cls.vols = {"long_hop": long_hop(), "long_stay": long_stay(), "short_hop": short_hop(), "apart": apart(),
                    "near_seed": short_hop_near_seed()}
        cls.v1 = {k: sf.barrier_keep(cls.xyz, cls.valid, field(v), SEED) for k, v in cls.vols.items()}
        cls.v2 = {}
        for k, v in cls.vols.items():
            try:
                cls.v2[k] = sf.barrier2_keep(cls.xyz, cls.valid, field(v), SEED)
            except sf.SwitchFixError as exc:
                cls.v2[k] = exc

    def test_constants(self):
        from kit import sheetgap
        self.assertEqual(sf.BARRIER2["sheetgap"], sf.BARRIER["sheetgap"])          # same one-sheet rule as v1
        self.assertEqual(sheetgap.rule_digest(sf.barrier_rule()), "24da24815958")
        self.assertEqual(len(sf.barrier2_digest()), 64)
        self.assertNotEqual(sf.barrier2_digest(), sf.barrier_digest())
        self.assertGreater(sf.BARRIER2["zone"]["group_dilate_cells"], 9)

    def test_parity_with_version_1(self):
        # control: version 2's code with version 1's zone setting and no seed guard must give version 1's cut on
        # every volume
        for k, v in self.vols.items():
            P = dict(params(**V1_ZONE), seed_max_vox=None)
            keep, info = sf.barrier2_keep(self.xyz, self.valid, field(v), SEED, P)
            self.assertTrue((keep == self.v1[k][0]).all(), k)
            self.assertEqual(info["barrier_points"], self.v1[k][1]["barrier_points"], k)

    def test_version_1_misses_the_long_merge(self):
        keep, info = self.v1["long_hop"]
        self.assertEqual(info["barrier_points"], 0)
        self.assertTrue(keep[self.X >= M1 + 60].all())          # the part on B stays attached

    def test_version_2_cuts_the_long_merge(self):
        keep, info = self.v2["long_hop"]
        self.assertGreater(info["barrier_points"], 0)
        self.assertFalse(keep[self.X >= M1].any())              # nothing past the merge
        self.assertTrue(keep[self.X <= 200].all())              # the seed's side stays whole

    def test_version_2_keeps_a_trace_that_stays_through_the_long_merge(self):
        keep, info = self.v2["long_stay"]
        self.assertEqual(info["barrier_points"], 0)
        self.assertTrue(keep[self.valid].all())

    def test_version_2_still_cuts_the_short_merge_with_a_wider_cut(self):
        k1, i1 = self.v1["short_hop"]
        k2, i2 = self.v2["short_hop"]
        self.assertGreater(i2["barrier_points"], 0)
        self.assertFalse(k1[self.X >= 530].any())                # v1 cuts it (the fixture can fail)
        self.assertFalse(k2[self.X >= 530].any())
        self.assertTrue(k2[self.X <= 300].all())                  # the seed's side up to the widened cut stays
        self.assertGreater(i2["barrier_points"], i1["barrier_points"])   # the price: a wider cut than v1's
        self.assertLessEqual(int(k2.sum()), int(k1.sum()))

    def test_near_marking_keeps_more_than_the_group_marking(self):
        # the code's other mode (mark "near"): same hop decision, narrower cut
        near = params(group_dilate_cells=27, mark="near", mark_dilate_cells=9)
        kn, _ = sf.barrier2_keep(self.xyz, self.valid, field(self.vols["long_hop"]), SEED, near)
        kg, _ = self.v2["long_hop"]
        self.assertFalse(kn[self.X >= M1].any())
        self.assertGreaterEqual(int(kn.sum()), int(kg.sum()))

    def test_version_1_keeps_the_far_side_when_the_seed_part_is_lost(self):
        # the failure the seed guard is for: v1 keeps a part away from the seed, past the hop
        keep, info = self.v1["near_seed"]
        self.assertFalse(keep[self.X <= 150].any())
        self.assertTrue(keep[self.X >= 400].any())
        self.assertGreater(info["seed_distance_vox"], 20.0)

    def test_seed_guard_refuses_when_the_seed_part_is_lost(self):
        self.assertIsInstance(self.v2["near_seed"], sf.SwitchFixError)
        self.assertIn("seed's own part", str(self.v2["near_seed"]))

    def test_barrier2_needs_a_seed(self):
        with self.assertRaises(sf.SwitchFixError) as cm:
            sf.barrier2_keep(self.xyz, self.valid, field(self.vols["apart"]), None)
        self.assertIn("needs a seed", str(cm.exception))
        # control: with the guard off (parity setting) no seed is needed
        keep, _ = sf.barrier2_keep(self.xyz, self.valid, field(self.vols["apart"]), None,
                                   dict(params(**V1_ZONE), seed_max_vox=None))
        self.assertTrue(keep[self.valid].all())

    def test_seed_guard_passes_a_seed_on_its_part(self):
        # control: the guard does not refuse where the seed's part survives
        for k in ("long_hop", "short_hop", "long_stay", "apart"):
            keep, info = self.v2[k]
            self.assertLessEqual(info["seed_distance_vox"], sf.BARRIER2["seed_max_vox"], k)

    def test_sheets_apart_keep_everything(self):
        keep, info = self.v2["apart"]
        self.assertEqual(info["barrier_points"], 0)
        self.assertTrue(keep[self.valid].all())

    def test_without_a_barrier_the_hop_is_joined(self):
        # control: the cut comes from the marked zone, not from the components
        cert, k, up, rule = sf.dense_cert(self.xyz, self.valid, field(self.vols["long_hop"]), sf.BARRIER2["sheetgap"])
        keep, _ = sf.keep_from_cert(cert, k, up, self.valid, rule, np.zeros(cert.ok.shape, bool), SEED)
        self.assertTrue(keep[self.X >= M1 + 60].all())

    def test_nothing_certified_refuses(self):
        with self.assertRaises(sf.SwitchFixError):
            sf.barrier2_keep(self.xyz, self.valid, field(np.zeros(SHAPE, np.uint8)), SEED)

    def test_barrier2_writes_kept_copy_and_record(self):
        from kit import meshqa
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            src.mkdir()
            for i, n in enumerate("xyz"):
                meshqa._write_grid(src / f"{n}.tif", self.xyz[..., i].astype(np.float32))
            (src / "meta.json").write_text(json.dumps({"format": "tifxyz", "seed": list(SEED)}))
            out = Path(td) / "out"
            rec = sf.barrier2(src, out, field(self.vols["long_hop"]), record_path=Path(td) / "r.json")
            self.assertEqual(rec["kept"], int(self.v2["long_hop"][0].sum()))
            self.assertEqual(rec["barrier2_digest"], sf.barrier2_digest())
            self.assertEqual(json.loads((Path(td) / "r.json").read_text())["kind"], "kit-switchfix-barrier2")
            self.assertTrue((out / "meta.json").is_file())


if __name__ == "__main__":
    unittest.main()
