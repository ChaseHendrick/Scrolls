"""Tests for kit.stackcheck on synthetic spiral stacks built here (no downloads).

A clean stack of six windings of an Archimedean spiral, each segment exactly one turn, passes every check; each
planted defect (a missing sector, two adjacent missing sectors, an inversion, a skipped winding, a turn overlap at
either end of the turn, a missing stack end, a winding traced twice, one missing all the way, a segment on its
neighbour's sheet) is flagged by its own check, so every check can fail; a check with nothing to look at keeps the
stack from being reported clean; and bad inputs and outputs exit 2."""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import numpy as np
    import scipy  # noqa: F401
    import tifffile
except ImportError:  # pragma: no cover
    np = None

from kit import cli, stackcheck as sc
from kit.verify import VerifyError

CX, CY = 2000.0, 2000.0
TILT = 0.01            # the synthetic umbilicus leans 0.01 voxel in x per voxel of z
R0, PITCH = 400.0, 50.0
SEAM = 17.3            # degrees: where every turn starts
H = 10.0               # grid step, voxels
Z0, Z1 = 0.0, 400.0
VOXEL_UM = 2.0         # pitch 100 um, half pitch 50 um, coincide 20 um = 10 voxels
SETTINGS = {"planes": 40}


def umbilicus():
    z = np.arange(-100.0, 501.0, 50.0)
    return {"control_points": [{"x": CX + TILT * v, "y": CY, "z": v} for v in z],
            "metadata": {"voxelsize_um": VOXEL_UM}}


def winding(k, extra_deg=0.0, z0=Z0, z1=Z1):
    """Segment k of the spiral r = R0 + PITCH * theta / 360, one turn from SEAM (plus extra_deg), rows along z."""
    th0 = SEAM + 360.0 * k
    th1 = th0 + 360.0 + extra_deg
    rmean = R0 + PITCH * (k + 0.5)
    ncol = int(np.ceil(np.radians(th1 - th0) * rmean / H)) + 1
    th = np.linspace(th0, th1, ncol)
    z = np.arange(z0, z1 + 0.5 * H, H)
    T, Zg = np.meshgrid(th, z)
    r = R0 + PITCH * (T - SEAM) / 360.0
    x = CX + TILT * Zg + r * np.cos(np.radians(T))
    y = CY + r * np.sin(np.radians(T))
    return np.stack([x, y, Zg], -1), np.ones(T.shape, bool), T


def stack(n=6):
    return [list(winding(k)) for k in range(n)]


def winding_from(k, th0, th1):
    """Segment k's sheet traced from angle th0 to th1 (degrees along the spiral, k turns from SEAM at th = SEAM)."""
    rmean = R0 + PITCH * (k + 0.5)
    ncol = int(np.ceil(np.radians(th1 - th0) * rmean / H)) + 1
    th = np.linspace(th0, th1, ncol)
    T, Zg = np.meshgrid(th, np.arange(Z0, Z1 + 0.5 * H, H))
    r = R0 + PITCH * (T - SEAM) / 360.0
    return [np.stack([CX + TILT * Zg + r * np.cos(np.radians(T)), CY + r * np.sin(np.radians(T)), Zg], -1),
            np.ones(T.shape, bool), T]


def copy_seg(seg):
    return [a.copy() for a in seg]


def radial_move(seg, sel, dr):
    xyz, _, T = seg
    u = np.stack([np.cos(np.radians(T)), np.sin(np.radians(T))], -1)
    xyz[..., :2] = np.where(sel[..., None], xyz[..., :2] + dr * u, xyz[..., :2])


def sector(seg, a0, a1, z0, z1):
    xyz, _, T = seg
    a = np.mod(T, 360.0)
    return (a >= a0) & (a <= a1) & (xyz[..., 2] >= z0) & (xyz[..., 2] <= z1)


def check(segs, settings=None):
    umb = sc.parse_umbilicus(umbilicus())
    objs = [sc.Segment(f"w{k:02d}", xyz, valid) for k, (xyz, valid, _) in enumerate(segs)]
    rep, masks = sc.check_stack(objs, umb, VOXEL_UM, dict(SETTINGS, **(settings or {})))
    return rep, masks


# The normal search is the slow part of check_stack, and most tests here plant one defect in an otherwise unchanged
# stack, so most of its work is the same from test to test. These wrappers keep each result under a digest of every
# input it reads and hand back that result (a fresh copy of each array) when exactly the same inputs come again: the
# real kit code still runs once for every distinct input, and what check_stack returns is unchanged.
_DENSE, _HITS = {}, {}


def _digest(*parts):
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, np.ndarray):
            h.update(repr((p.dtype.str, p.shape)).encode())
            h.update(np.ascontiguousarray(p).tobytes())
        else:
            h.update(repr(p).encode())
        h.update(b"|")
    return h.hexdigest()


def _cached_dense(seg, k, umb, _dense=sc.Dense):
    key = _digest(seg.xyz, seg.valid, seg.step, seg.rmed, k, umb.z, umb.x, umb.y)
    if key not in _DENSE:
        D = _dense(seg, k, umb)
        D.memo_key = key
        _DENSE[key] = D
    return _DENSE[key]


def _cached_normal_hits(P, N, D, maxd, foot, _hits=sc.normal_hits, **kw):
    key = _digest(P, N, D.memo_key, maxd, foot, sorted(kw.items()))
    if key not in _HITS:
        _HITS[key] = _hits(P, N, D, maxd, foot, **kw)
    return tuple(a.copy() for a in _HITS[key])


_PATCHES = []


def setUpModule():
    if np is None:
        return
    for name, fn in (("Dense", _cached_dense), ("normal_hits", _cached_normal_hits)):
        p = mock.patch.object(sc, name, fn)
        p.start()
        _PATCHES.append(p)


def tearDownModule():
    while _PATCHES:
        _PATCHES.pop().stop()
    _DENSE.clear()
    _HITS.clear()


def write_tifxyz(d, xyz, valid):
    d.mkdir(parents=True)
    for i, c in enumerate("xyz"):
        tifffile.imwrite(str(d / f"{c}.tif"), np.where(valid, xyz[..., i], -1.0).astype(np.float32))
    (d / "meta.json").write_text(json.dumps({"format": "tifxyz", "type": "seg", "scale": [0.05, 0.05]}))


@unittest.skipIf(np is None, "numpy, scipy and tifffile are needed")
class CleanStackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep, cls.masks = check(stack())

    def test_clean_stack_passes_every_check(self):
        s = self.rep["summary"]
        self.assertTrue(s["clean"], s["flagged"])
        self.assertTrue(all(v == [] for v in s["flagged"].values()))
        self.assertIn("coincident_pairs", s["flagged"])
        self.assertIn("pair_spacing", s["flagged"])
        # what no check can see is named in every report
        self.assertTrue(any("w00 and w05" in m for m in s["not_covered"]), s["not_covered"])

    def test_spacing_and_pitch_are_measured(self):
        for p in self.rep["order"]["pairs"]:
            self.assertEqual(p["inverted_rays"], 0)
            self.assertEqual(p["within_coincide_rays"], 0)
            self.assertAlmostEqual(p["spacing_against_nearby_pairs"], 1.0, delta=0.02)
            self.assertGreater(p["rays"], 1000)
            self.assertAlmostEqual(p["spacing_um_q10_25_50_75_90"][2], PITCH * VOXEL_UM, delta=2.0)
        for s in self.rep["segments"]:
            self.assertAlmostEqual(s["local_pitch_um"], PITCH * VOXEL_UM, delta=2.0)

    def test_no_mask_marks_a_vertex_but_the_seams(self):
        for name, m in self.masks.items():
            for key in ("order", "missing_sector", "skipped_winding", "turn_overlap"):
                self.assertEqual(int(m[key].sum()), 0, f"{name} {key}")
            # where one turn ends and the next starts, two segments meet: at most one grid column each side
            self.assertLessEqual(int(m["coincident"].sum()), 2 * m["coincident"].shape[0], name)


@unittest.skipIf(np is None, "numpy, scipy and tifffile are needed")
class PlantedDefectTest(unittest.TestCase):
    def test_missing_sector(self):
        segs = stack()
        segs[2][1] &= ~sector(segs[2], 100, 160, 100, 300)
        rep, masks = check(segs)
        self.assertEqual(rep["summary"]["flagged"]["missing_sectors"], ["w02"])
        for key in ("order", "order_vertices", "skipped_windings", "turn_overlaps", "stack_ends"):
            self.assertEqual(rep["summary"]["flagged"][key], [], key)
        r = next(x for x in rep["missing_sectors"] if x["segment"] == "w02")
        ext = r["gap_extent"]
        self.assertGreaterEqual(ext["z"][0], 95)
        self.assertLessEqual(ext["z"][1], 305)
        self.assertTrue(98 <= ext["start_deg"][0] <= 105 and 98 <= ext["start_deg"][1] <= 105, ext)
        self.assertTrue(155 <= ext["end_deg"][0] <= 162 and 155 <= ext["end_deg"][1] <= 162, ext)
        for p in r["per_plane"]:            # the width is the angle from the first gap ray to the last
            self.assertAlmostEqual(p["width_deg"], (p["end_deg"] - p["start_deg"]) % 360, delta=0.2)
        self.assertTrue(r["gap_by_height"])
        for b in r["gap_by_height"]:
            self.assertAlmostEqual(b["median_um"]["w01 to w03"], 2 * PITCH * VOXEL_UM, delta=3)
            self.assertAlmostEqual(b["median_um"]["w00 to w03"], 3 * PITCH * VOXEL_UM, delta=3)
        self.assertEqual(rep["summary"]["flagged"]["missing_runs"], [])
        # the neighbours lie two pitches apart in the gap and elsewhere alike
        sp = r["neighbour_spacing"]
        self.assertGreater(sp["gap"]["rays"], 100)
        self.assertAlmostEqual(sp["gap"]["median_um"], 2 * PITCH * VOXEL_UM, delta=3)
        self.assertAlmostEqual(sp["present"]["median_um"], 2 * PITCH * VOXEL_UM, delta=3)
        for name in ("w01", "w03"):
            v = r["neighbour_vertices"][name]
            self.assertGreater(v["vertices"], 50)
            self.assertTrue(masks[name]["missing_sector"].any())
            a = circ = v["angle_deg"]
            self.assertTrue(95 <= circ[0] <= 106 and 154 <= circ[1] <= 165, a)
        self.assertFalse(masks["w00"]["missing_sector"].any())

    def test_inversion(self):
        segs = stack()
        sel = sector(segs[2], 200, 260, 150, 250)
        radial_move(segs[2], sel, 1.35 * PITCH)        # w02 lies 0.35 pitch outside w03 there
        rep, masks = check(segs)
        f = rep["summary"]["flagged"]
        self.assertIn("w02/w03", f["order"])
        self.assertEqual(f["skipped_windings"], [])
        self.assertEqual(f["missing_sectors"], [])
        p = next(x for x in rep["order"]["pairs"] if x["inner"] == "w02")
        self.assertGreater(p["inverted_share"], 0.02)
        self.assertAlmostEqual(p["inverted"]["depth_um_q25_50_75"][1], 0.35 * PITCH * VOXEL_UM, delta=3)
        lo, hi, _ = p["inverted"]["angle_deg"]
        self.assertTrue(195 <= lo <= 205 and 255 <= hi <= 265, p["inverted"])
        self.assertTrue(set(f["order_vertices"]) & {"w02", "w03"}, f)
        v = next(x for x in rep["order"]["vertices"] if x["segment"] == "w03")
        g = next(x for x in v["groups"] if x["neighbour"] == "w02")
        self.assertEqual(g["side"], "outer")
        self.assertAlmostEqual(g["distance_um_q25_50_75"][1], 0.35 * PITCH * VOXEL_UM, delta=4)
        self.assertTrue(masks["w02"]["order"].any() and masks["w03"]["order"].any())

    def test_inversion_within_coincide_distance_is_not_flagged(self):
        segs = stack()
        sel = sector(segs[2], 200, 260, 150, 250)
        radial_move(segs[2], sel, PITCH + 1.3)          # w02 lies 2.6 um outside w03: within --coincide-um
        rep, _ = check(segs)
        p = next(x for x in rep["order"]["pairs"] if x["inner"] == "w02")
        self.assertGreater(p["inverted_rays"], 100)
        self.assertEqual(p["inverted_beyond_coincide_rays"], 0)
        self.assertEqual(rep["summary"]["flagged"]["order"], [])
        # there the two cannot be told apart, which is flagged as such
        self.assertEqual(rep["summary"]["flagged"]["coincident_pairs"], ["w02/w03"])
        self.assertGreaterEqual(p["within_coincide_rays"], p["inverted_rays"])

    def test_two_adjacent_missing_sectors(self):
        segs = stack()
        for k in (2, 3):
            segs[k][1] &= ~sector(segs[k], 100, 160, 100, 300)
        rep, masks = check(segs)
        f = rep["summary"]["flagged"]
        self.assertEqual(f["missing_runs"], ["w01/w04"])
        self.assertEqual(f["missing_sectors"], [])
        self.assertFalse(rep["summary"]["clean"])
        r = next(x for x in rep["missing_runs"] if x["between"] == ["w01", "w04"])
        self.assertEqual(r["missing"], ["w02", "w03"])
        self.assertTrue(95 <= r["angle_deg"][0] <= 106 and 154 <= r["angle_deg"][1] <= 165, r)
        self.assertGreaterEqual(r["z"][0], 95)
        self.assertLessEqual(r["z"][1], 305)
        self.assertAlmostEqual(r["spacing"]["hole"]["median_um"], 3 * PITCH * VOXEL_UM, delta=3)
        for name in ("w01", "w04"):
            self.assertGreater(r["bounding_vertices"][name]["vertices"], 50)
            self.assertTrue(masks[name]["missing_sector"].any())
            self.assertTrue(masks[name]["any"].any())
        for name in ("w00", "w05"):
            self.assertFalse(masks[name]["missing_sector"].any(), name)

    def test_skipped_winding(self):
        segs = stack()
        segs[3][1] &= ~sector(segs[3], 40, 120, 120, 280)          # w03 missing there
        radial_move(segs[4], sector(segs[4], 55, 105, 150, 250), -1.7 * PITCH)   # w04 0.3 pitch outside w02
        rep, masks = check(segs)
        f = rep["summary"]["flagged"]
        self.assertIn("w02", f["skipped_windings"])
        self.assertIn("w04", f["skipped_windings"])
        self.assertIn("w03", f["missing_sectors"])
        self.assertEqual(f["order"], [])
        r = next(x for x in rep["skipped_windings"] if x["segment"] == "w02")
        self.assertEqual(r["groups"][0]["neighbour"], "w04")
        self.assertEqual(r["groups"][0]["side"], "outer")
        self.assertAlmostEqual(r["distance_um_q25_50_75"][1], 0.3 * PITCH * VOXEL_UM, delta=3)
        self.assertAlmostEqual(r["limit_um"], 0.5 * PITCH * VOXEL_UM, delta=2)
        self.assertGreater(r["in_missing_sector_share"], 0.9)
        self.assertTrue(r["examples"])
        self.assertEqual(r["examples"][0]["nearest_outer"]["segment"], "w04")
        self.assertFalse(masks["w01"]["skipped_winding"].any())
        # w02 to w04 sit 0.3 pitch apart where w03 is missing, against two pitches elsewhere
        m = next(x for x in rep["missing_sectors"] if x["segment"] == "w03")
        self.assertLess(m["neighbour_spacing"]["gap"]["um_q10_25_50_75_90"][0], 0.35 * PITCH * VOXEL_UM)
        self.assertAlmostEqual(m["neighbour_spacing"]["present"]["median_um"], 2 * PITCH * VOXEL_UM, delta=3)

    def test_turn_overlap(self):
        segs = stack()
        segs[2] = list(winding(2, extra_deg=40.0))        # w02 runs on 40 degrees, onto w03's sheet
        rep, masks = check(segs)
        f = rep["summary"]["flagged"]
        self.assertEqual(f["turn_overlaps"], ["w02"])
        self.assertEqual(f["order"], [])
        self.assertEqual(f["order_vertices"], [])
        self.assertEqual(f["skipped_windings"], [])
        r = next(x for x in rep["turn_overlaps"] if x["segment"] == "w02")
        self.assertAlmostEqual(r["past_full_turn_deg_q10_25_50_75_90"][2], 40.0, delta=1.0)
        self.assertEqual(r["lines_past_full_turn"], r["lines"])
        lo, hi, _ = r["doubly_traced_end"]["angle_deg"]
        self.assertTrue(SEAM - 2 <= lo <= SEAM + 2 and SEAM + 38 <= hi <= SEAM + 42, r["doubly_traced_end"])
        self.assertEqual(r["doubly_traced_end"]["end_of_turn"], "end")
        self.assertEqual(r["doubly_traced_end"]["piece"], "outer")
        self.assertEqual((r["neighbour"]["segment"], r["neighbour"]["side"]), ("w03", "outer"))
        self.assertLess(r["neighbour"]["distance_um_q5_25_50_75_95"][2], 1.0)
        self.assertGreater(r["neighbour"]["vertices_at_same_height_and_angle"], 50)
        self.assertTrue(masks["w03"]["turn_overlap"].any())
        self.assertFalse(masks["w04"]["turn_overlap"].any())
        self.assertFalse(masks["w01"]["turn_overlap"].any())
        T = segs[2][2]
        late, early = T > T[:, :1] + 361.0, T < T[:, :1] + 39.0
        self.assertTrue(masks["w02"]["turn_overlap"][late].all())
        self.assertFalse(masks["w02"]["turn_overlap"][early].any())

    def test_turn_overlap_at_the_start_of_the_turn(self):
        segs = stack()
        th0 = SEAM + 720.0
        segs[2] = winding_from(2, th0 - 40.0, th0 + 360.0)   # w02 starts 40 degrees early, on w01's sheet
        rep, masks = check(segs)
        f = rep["summary"]["flagged"]
        self.assertEqual(f["turn_overlaps"], ["w02"])
        self.assertEqual(f["order"], [])
        self.assertEqual(f["skipped_windings"], [])
        r = next(x for x in rep["turn_overlaps"] if x["segment"] == "w02")
        self.assertAlmostEqual(r["past_full_turn_deg_q10_25_50_75_90"][2], 40.0, delta=1.0)
        self.assertEqual(r["doubly_traced_end"]["piece"], "inner")
        self.assertEqual((r["neighbour"]["segment"], r["neighbour"]["side"]), ("w01", "inner"))
        self.assertLess(r["neighbour"]["distance_um_q5_25_50_75_95"][2], 1.0)
        T = segs[2][2]
        early, late = T < th0, T > th0 + 321.0
        self.assertTrue(masks["w02"]["turn_overlap"][early].all())
        self.assertFalse(masks["w02"]["turn_overlap"][late].any())
        self.assertGreater(int(masks["w01"]["turn_overlap"].sum()), 50)
        self.assertFalse(masks["w03"]["turn_overlap"].any())
        # 30 um off w01's sheet (beyond --coincide-um) the early part is still found
        segs2 = [copy_seg(x) for x in segs]
        radial_move(segs2[2], early, 15.0)
        rep2, masks2 = check(segs2)
        r2 = next(x for x in rep2["turn_overlaps"] if x["segment"] == "w02")
        self.assertEqual(r2["neighbour"]["segment"], "w01")
        self.assertTrue(masks2["w02"]["turn_overlap"][early].all())

    def test_turn_overlap_across_a_hole_wider_than_half_a_turn(self):
        segs = stack()
        segs[2] = list(winding(2, extra_deg=40.0))
        xyz, valid, T = segs[2]
        a = T - T[:, :1]                                  # angle along each line from its start
        valid &= ~((a > 100) & (a < 300) & (xyz[..., 2] >= 100) & (xyz[..., 2] <= 300))
        rep, masks = check(segs)
        r = next(x for x in rep["turn_overlaps"] if x["segment"] == "w02")
        self.assertEqual(r["lines_past_full_turn"], r["lines"])
        self.assertAlmostEqual(r["past_full_turn_deg_q10_25_50_75_90"][0], 40.0, delta=1.0)
        self.assertIn("w02", rep["summary"]["flagged"]["turn_overlaps"])
        self.assertTrue(masks["w03"]["turn_overlap"].any())

    def test_missing_stack_end(self):
        segs = stack()
        segs[3][1] &= segs[3][0][..., 2] >= 150
        rep, masks = check(segs)
        f = rep["summary"]["flagged"]
        self.assertEqual(f["stack_ends"], ["w03"])
        self.assertEqual(f["missing_sectors"], [])
        r = next(x for x in rep["stack_ends"] if x["segment"] == "w03")
        self.assertEqual(r["missing_below"]["between"], ["w02", "w04"])
        self.assertEqual(r["missing_below"]["z"], [0, 150])
        self.assertNotIn("missing_above", r)
        m = next(x for x in rep["missing_sectors"] if x["segment"] == "w03")
        self.assertEqual(m["gap_rays"], 0)
        self.assertGreater(m["gap_rays_outside_own_height"], 1000)
        # below w03 its neighbours are simply two windings apart: no gap spacing, no missing-sector mask, but the
        # neighbours' vertices there are on the stack-end mask
        self.assertEqual(m["neighbour_spacing"]["gap"]["rays"], 0)
        self.assertNotIn("gap_by_height", m)
        for name in masks:
            self.assertFalse(masks[name]["missing_sector"].any(), name)
        for name in ("w02", "w04"):
            z = segs[int(name[1:])][0][..., 2]
            self.assertTrue(masks[name]["stack_end"][z < 140].all(), name)
            self.assertFalse(masks[name]["stack_end"][z > 160].any(), name)
        self.assertFalse(masks["w01"]["stack_end"].any())

    def test_a_winding_traced_twice(self):
        base = stack(5)
        for shift in (0.0, 2.5):          # the same sheet, and the same sheet 5 um out
            dup = copy_seg(base[2])
            radial_move(dup, np.ones(dup[1].shape, bool), shift)
            rep, _ = check([base[0], base[1], base[2], dup, base[3], base[4]])
            f = rep["summary"]["flagged"]
            self.assertEqual(f["coincident_pairs"], ["w02/w03"], shift)
            self.assertEqual(f["pair_spacing"], ["w02/w03"], shift)
            self.assertFalse(rep["summary"]["clean"])
            p = next(x for x in rep["order"]["pairs"] if x["inner"] == "w02")
            self.assertGreater(p["within_coincide_share"], 0.99)
            self.assertLess(p["spacing_against_nearby_pairs"], 0.1)
            self.assertTrue(any("order per vertex w02" in m for m in rep["summary"]["not_checked"]))

    def test_a_winding_missing_all_the_way(self):
        base = stack(7)
        rep, _ = check([base[0], base[1], base[2], base[4], base[5], base[6]])
        f = rep["summary"]["flagged"]
        self.assertEqual(f["pair_spacing"], ["w02/w03"])
        self.assertEqual(f["coincident_pairs"], [])
        p = next(x for x in rep["order"]["pairs"] if x["inner"] == "w02")
        self.assertAlmostEqual(p["spacing_against_nearby_pairs"], 2.0, delta=0.05)

    def test_a_segment_on_its_neighbours_sheet_over_a_sector(self):
        segs = stack()
        radial_move(segs[3], sector(segs[3], 100, 160, 100, 300), -PITCH)
        rep, _ = check(segs)
        f = rep["summary"]["flagged"]
        self.assertEqual(f["coincident_pairs"], ["w02/w03"])
        self.assertEqual(f["order"], [])
        self.assertEqual(f["pair_spacing"], [])

    def test_control_pairs_keep_their_spacing(self):
        segs = stack(8)
        segs[2][1] &= ~sector(segs[2], 100, 160, 100, 300)
        rep, _ = check(segs)
        r = next(x for x in rep["missing_sectors"] if x["segment"] == "w02")
        c = next(x for x in r["control_pairs"] if x["pair"] == ["w03", "w07"])
        self.assertGreater(c["gap"]["rays"], 100)
        self.assertAlmostEqual(c["gap"]["median_um"], 4 * PITCH * VOXEL_UM, delta=3)
        self.assertAlmostEqual(c["present"]["median_um"], 4 * PITCH * VOXEL_UM, delta=3)


@unittest.skipIf(np is None, "numpy, scipy and tifffile are needed")
class NothingToLookAtTest(unittest.TestCase):
    def test_planes_outside_the_stack_are_bad_input(self):
        with self.assertRaises(VerifyError):
            check(stack(), {"planes": None, "plane_z": (1000, 2000, 10)})

    def test_no_neighbour_along_the_normal_is_not_clean(self):
        rep, _ = check(stack(), {"max_normal_um": 1.0})
        self.assertFalse(rep["summary"]["clean"])
        self.assertTrue(all(v == [] for v in rep["summary"]["flagged"].values()), rep["summary"]["flagged"])
        self.assertTrue(any("vertex checks" in m for m in rep["summary"]["not_checked"]))

    def test_a_pair_no_ray_crosses_is_not_clean(self):
        segs = stack()
        segs[3][1] &= segs[3][0][..., 2] >= 250
        rep, _ = check(segs, {"planes": None, "plane_z": (20, 200, 20)})
        self.assertFalse(rep["summary"]["clean"])
        self.assertIn("order w02/w03: no ray crosses both once", rep["summary"]["not_checked"])

    def test_bad_settings(self):
        for bad in ({"ray_step_deg": 0}, {"ray_step_deg": -1}, {"ray_step_deg": 11}, {"ray_step_deg": 360},
                    {"planes": 0}, {"planes": -1}, {"upsample": -3}, {"max_normal_um": 0}, {"coincide_um": -1},
                    {"min_share": 2}, {"skip_frac": 0}, {"min_count": 0}, {"planes": 10, "plane_z": (0, 100, 10)}):
            with self.assertRaises(VerifyError, msg=str(bad)):
                sc.check_settings(bad)
        self.assertEqual(sc.check_settings({"planes": 7})["planes"], 7)
        self.assertIsNone(sc.check_settings({"plane_z": (0, 100, 10)})["planes"])

    def test_a_coincide_distance_over_the_pitch_is_not_clean(self):
        segs = stack()
        radial_move(segs[2], sector(segs[2], 200, 260, 150, 250), 1.35 * PITCH)
        rep, _ = check(segs, {"coincide_um": 150})
        self.assertFalse(rep["summary"]["clean"])
        self.assertTrue(any("order per vertex" in m for m in rep["summary"]["not_checked"]), rep["summary"])

    def test_the_end_segments_are_named_as_not_covered(self):
        segs = stack()
        segs[0][1] &= ~sector(segs[0], 100, 160, 100, 300)
        rep, _ = check(segs)
        self.assertEqual(rep["summary"]["flagged"]["missing_sectors"], [])
        self.assertIn("missing sectors of w00 and w05: the innermost and outermost segments have a neighbour on one "
                      "side only", rep["summary"]["not_covered"])


@unittest.skipIf(np is None, "numpy, scipy and tifffile are needed")
class InputsTest(unittest.TestCase):
    def test_cli_on_files_with_a_transform_writes_report_and_masks(self):
        segs = stack()
        segs[2][1] &= ~sector(segs[2], 100, 160, 100, 300)
        M = np.array([[2.0, 0.0, 0.0, 10.0], [0.0, 2.0, 0.0, -20.0], [0.0, 0.0, 2.0, 30.0]])
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            args = []
            for k, (xyz, valid, _) in enumerate(segs):
                # stored in a volume at twice the voxel size; the transform maps back into the umbilicus's
                back = (xyz - M[:, 3]) / 2.0
                write_tifxyz(t / f"seg{k}" / "mesh" / f"seg{k}-on-vol-4.000um.tifxyz", back, valid)
                args.append(str(t / f"seg{k}" / "mesh" / f"seg{k}-on-vol-4.000um.tifxyz"))
            (t / "umb.json").write_text(json.dumps(umbilicus()))
            (t / "m.json").write_text(json.dumps({"matrix": M.tolist()}))
            out, flags = t / "rep.json", t / "flags.npz"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.main(["stackcheck", *args, "--umbilicus", str(t / "umb.json"), "--transform",
                                 str(t / "m.json"), "--planes", "40", "--out", str(out), "--flags", str(flags)])
            self.assertEqual(code, 1, buf.getvalue())
            self.assertIn("missing sectors", buf.getvalue())
            rep = json.loads(out.read_text())
            self.assertEqual(rep["summary"]["flagged"]["missing_sectors"], ["seg2"])
            self.assertEqual(rep["frame"]["voxel_um"], VOXEL_UM)
            self.assertEqual(rep["frame"]["voxel_um_from"], "umbilicus metadata")
            ex = rep["missing_sectors"][1]["neighbour_vertices"]["seg1"]
            self.assertGreater(ex["vertices"], 50)
            z = np.load(flags)
            self.assertEqual(z["seg1/missing_sector"].shape, segs[1][1].shape)
            self.assertTrue(z["seg1/missing_sector"].any() and z["seg1/any"].any())
            self.assertFalse(z["seg0/any"][:, 5:-5].any())
            # without the transform the voxel sizes disagree, so the run stops with a reason
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(["stackcheck", *args, "--umbilicus", str(t / "umb.json")])
            self.assertEqual(code, 2)
            self.assertIn("--transform", err.getvalue())

    def test_stride_keeps_the_input_grid_for_masks(self):
        segs = stack(4)
        segs[1][1] &= ~sector(segs[1], 100, 160, 100, 300)
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            paths = []
            for k, (xyz, valid, _) in enumerate(segs):
                write_tifxyz(t / f"w{k}", xyz, valid)
                paths.append(f"name{k}={t / f'w{k}'}")
            (t / "umb.json").write_text(json.dumps(umbilicus()))
            rep, objs, masks = sc.run(paths, str(t / "umb.json"), stride=2, settings=SETTINGS)
            self.assertEqual([s.name for s in objs], ["name0", "name1", "name2", "name3"])
            self.assertEqual(rep["summary"]["flagged"]["missing_sectors"], ["name1"])
            sc.write_flags(t / "f.npz", objs, masks, VOXEL_UM)
            z = np.load(t / "f.npz")
            self.assertEqual(z["name0/missing_sector"].shape, segs[0][1].shape)
            self.assertTrue(z["name0/missing_sector"].any())

    def test_names_and_urls(self):
        self.assertEqual(sc.segment_name("PHerc0139/segments/20260317000000-w035_2026031718/mesh/"
                                         "20260317000000-on-20260102150214-2.399um.tifxyz"),
                         "20260317000000-w035_2026031718")
        self.assertEqual(sc.segment_name("s3://vesuvius-challenge-open-data/PHerc0139/segments/x-w033_1/mesh/"
                                         "a-on-b-9.362um.tifxyz/"), "x-w033_1")
        self.assertEqual(sc._https("s3://vesuvius-challenge-open-data/PHerc0139/a"), sc.BUCKET + "/PHerc0139/a")
        self.assertEqual(sc.folder_voxel_um("x/a-on-b-2.399um.tifxyz"), 2.399)
        self.assertIsNone(sc.folder_voxel_um("refs/meshes/w035"))
        with self.assertRaises(VerifyError):
            sc.fetch_tifxyz("https://example.org/a/../b.tifxyz", tempfile.gettempdir())

    def test_a_path_with_an_equals_sign(self):
        self.assertEqual(sc.split_spec("w035=/data/a/b.tifxyz"), ("w035", "/data/a/b.tifxyz"))
        self.assertEqual(sc.split_spec("/data/run=1/w0"), (None, "/data/run=1/w0"))
        self.assertEqual(sc.split_spec("w1=https://x.org/a=b"), ("w1", "https://x.org/a=b"))
        with tempfile.TemporaryDirectory() as t:
            here = Path.cwd()
            try:
                os.chdir(t)
                Path("run=1").mkdir()               # an existing folder is a path, even without a separator
                self.assertEqual(sc.split_spec("run=1"), (None, "run=1"))
                self.assertEqual(sc.split_spec("w0=run=1"), ("w0", "run=1"))
            finally:
                os.chdir(here)

    def test_catalog_transform_and_volume_checks(self):
        segs = stack()
        segs[2][1] &= ~sector(segs[2], 100, 160, 100, 300)
        M = np.array([[2.0, 0.0, 0.0, 10.0], [0.0, 2.0, 0.0, -20.0], [0.0, 0.0, 2.0, 30.0]])
        cat = {"samples": {"S1": {"sample": {"properties": {"volume_transforms": [
            {"from_volume_id": "volA", "transforms": [{"to_volume_id": "volB", "matrix": M.tolist()}]}]}}}}}
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            args = []
            for k, (xyz, valid, _) in enumerate(segs):
                d = t / f"s{k}" / "mesh" / f"s{k}-on-volA-4.000um.tifxyz"
                write_tifxyz(d, (xyz - M[:, 3]) / 2.0, valid)
                args.append(f"w{k}={d}")
            u = dict(umbilicus(), metadata={"voxelsize_um": VOXEL_UM, "volume": "volB-2.000um-x.zarr"})
            (t / "umb.json").write_text(json.dumps(u))
            (t / "cat.json").write_text(json.dumps(cat))
            rep, _, _ = sc.run(args, str(t / "umb.json"), "catalog:S1:volA:volB", str(t / "cat.json"),
                               settings=SETTINGS)
            self.assertEqual(rep["summary"]["flagged"]["missing_sectors"], ["w2"])
            self.assertEqual(rep["frame"]["volumes"], {"segments": "volA", "umbilicus": "volB"})
            self.assertEqual(np.round(rep["transform"], 6).tolist(), M.tolist())
            for spec, msg in (("catalog:S1:volA:volC", "ends on volume volC"),
                              ("catalog:S1:volX:volB", "starts on volume volX"),
                              ("catalog:S2:volA:volB", None)):
                with self.assertRaises((VerifyError, KeyError), msg=spec) as cm:
                    sc.run(args, str(t / "umb.json"), spec, str(t / "cat.json"), settings=SETTINGS)
                if msg:
                    self.assertIn(msg, str(cm.exception))
            # without the transform, the folder names' volume differs from the umbilicus's
            with self.assertRaises(VerifyError):
                sc.run(args, str(t / "umb.json"), settings=SETTINGS)
            # copies on two volumes under one transform
            mixed = list(args)
            d = t / "s9" / "mesh" / "s9-on-volZ-4.000um.tifxyz"
            write_tifxyz(d, segs[0][0], segs[0][1])
            mixed[0] = f"w0={d}"
            with self.assertRaises(VerifyError):
                sc.run(mixed, str(t / "umb.json"), "catalog:S1:volA:volB", str(t / "cat.json"), settings=SETTINGS)
            # a 4x4 matrix must end in [0, 0, 0, 1]
            bad = np.vstack([M, [0.5, 0.0, 0.0, 2.0]])
            (t / "m44.json").write_text(json.dumps(bad.tolist()))
            with self.assertRaises(VerifyError):
                sc.load_transform(str(t / "m44.json"))
            good = np.vstack([M, [0.0, 0.0, 0.0, 1.0]])
            (t / "m44.json").write_text(json.dumps(good.tolist()))
            self.assertEqual(sc.load_transform(str(t / "m44.json")).tolist(), M.tolist())

    def test_cli_exit_codes(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "umb.json").write_text(json.dumps(umbilicus()))
            base = ["stackcheck", "a", "b", "c", "--umbilicus", str(Path(t) / "umb.json")]
            for extra in (["--ray-step-deg", "0"], ["--planes", "-1"], ["--planes", "5", "--plane-z", "0", "9", "1"]):
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(base + extra), 2, extra)
            real = sc.run
            try:
                sc.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(base), 2)
            finally:
                sc.run = real
        self.assertIn("unexpected error", err.getvalue())

    def test_cli_outputs(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            args = []
            for k, (xyz, valid, _) in enumerate(stack(4)):
                write_tifxyz(t / f"w{k}", xyz, valid)
                args.append(f"w{k}={t / f'w{k}'}")
            (t / "umb.json").write_text(json.dumps(umbilicus()))
            (t / "adir").mkdir()
            (t / "afile").write_text("x")
            base = ["stackcheck", *args, "--umbilicus", str(t / "umb.json"), "--planes", "20"]
            for out in (t / "adir", t / "afile" / "rep.json"):      # an output that cannot be written exits 2
                err = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(base + ["--out", str(out)]), 2, out)
                self.assertIn("could not read or write", err.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(base + ["--out", str(t / "rep.json"), "--flags", str(t / "masks")])
            self.assertEqual(code, 0)
            rep = json.loads((t / "rep.json").read_text())
            self.assertEqual(rep["flags_file"], str(t / "masks.npz"))
            self.assertTrue((t / "masks.npz").is_file())
            self.assertIsNone(rep["settings"]["planes"] if rep["settings"]["plane_z"] else None)
            # --voxel-um must agree with the umbilicus's metadata
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(base + ["--voxel-um", "9.362"]), 2)
            self.assertIn("--voxel-um", err.getvalue())

    def test_umbilicus_voxel_size_must_be_a_number_above_0(self):
        for bad in (-2.0, 0, float("nan"), "abc"):
            with self.assertRaises(VerifyError, msg=str(bad)):
                sc.parse_umbilicus(dict(umbilicus(), metadata={"voxelsize_um": bad}))
        pts = umbilicus()["control_points"]
        with self.assertRaises(VerifyError):
            sc.parse_umbilicus({"control_points": [dict(pts[0], x=float("nan"))] + pts[1:]})
        self.assertEqual(sc.parse_umbilicus(umbilicus()).voxel_um, VOXEL_UM)

    def test_too_few_segments_and_bad_umbilicus(self):
        with self.assertRaises(VerifyError):
            check(stack(2))
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "u.json"
            p.write_text(json.dumps([[0, 1, 2]]))
            with self.assertRaises(VerifyError):
                sc.load_umbilicus(str(p))


if __name__ == "__main__":
    unittest.main()
