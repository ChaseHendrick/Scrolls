"""kit surfbench on small synthetic stacks: an Archimedean spiral of windings written as tifxyz, with a copy that
moved part of itself one winding out (like w046), an ambiguous copy (like w041/w042), a partial winding, a contact
bulge and a missing winding. No network: the prediction chunks come from a synthetic reader."""

import copy
import json
import math
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:
    np = None

from kit import surfbench as sb

R0, PITCH, CX, CY, Z0, Z1, STEP = 400.0, 16.0, 1000.0, 1000.0, 1000.0, 1600.0, 20.0


def spiral_r(theta):
    return R0 + PITCH * theta / (2 * math.pi)


def wave(z):
    """Radial wobble along z, so that no winding is a prism and a patch moved in z leaves its winding."""
    return 6.0 * np.sin(2 * math.pi * z / 300.0)


def winding(k, t0=0.0, t1=2 * math.pi, offset=None, rows=None, ncol=None):
    """Grid of turn k of the spiral between angles t0 and t1 (within the turn), about STEP voxels apart."""
    th_a, th_b = 2 * math.pi * k + t0, 2 * math.pi * k + t1
    r_mid = spiral_r(0.5 * (th_a + th_b))
    ncol = ncol or max(3, int(round((th_b - th_a) * r_mid / STEP)) + 1)
    th = np.linspace(th_a, th_b, ncol)
    z = np.arange(Z0, Z1 + 1e-6, STEP) if rows is None else rows
    T, Z = np.meshgrid(th, z)
    r = spiral_r(T) + wave(Z)
    if offset is not None:
        r = r + offset(T - 2 * math.pi * k, Z)
    xyz = np.stack([CX + r * np.cos(T), CY + r * np.sin(T), Z], -1)
    return xyz, np.ones(T.shape, bool)


def bump(lo=120.0, hi=220.0, height=13.0):
    """Turn pressed inward by `height` voxels between lo and hi degrees (smooth 10 degree edges)."""
    def f(t, z):
        deg = np.degrees(t)
        return -height * np.clip((deg - lo) / 10, 0, 1) * np.clip((hi - deg) / 10, 0, 1)
    return f


def stack(root):
    """Eight meshes, named against their radial order so that only geometry can order them:
    turn 0 'w105', turn 1 'w101' (pressed to 3 voxels from turn 0 between 120 and 220 degrees), turn 2 'w103',
    'w104' a copy of turn 2 whose part between 200 and 300 degrees moved one turn out (turn 3 has no mesh of its
    own), turn 4 'w100', turn 5 'w102', 'w106' a copy of turn 5 that wanders between 230 and 330 degrees, turn 6
    'w107' only 0 to 150 degrees. Sites for the controls sit at 30 to 90 degrees, clear of all of these."""
    def moved(t, z):
        deg = np.degrees(t)
        return PITCH * np.clip((deg - 190) / 10, 0, 1) * np.clip((310 - deg) / 10, 0, 1)

    def wander(t, z):
        deg = np.degrees(t)
        inside = (deg > 230) & (deg < 330)
        return np.where(inside, 14 * np.sin((deg - 230) / 100 * 3 * math.pi) * np.sign(z - 1300 + 1e-9), 0.0)

    meshes = {
        "w105": winding(0), "w101": winding(1, offset=bump()), "w103": winding(2),
        "w104": winding(2, offset=moved), "w100": winding(4), "w102": winding(5), "w106": winding(5, offset=wander),
        "w107": winding(6, 0.0, math.radians(150)),
    }
    out = {}
    for name, (xyz, valid) in meshes.items():
        out[name] = sb.write_tifxyz(Path(root) / "meshes" / name, xyz, valid)
    return out


class SyntheticPrediction:
    """Chunks of a prediction holding the spiral's sheets (255 within 1.5 voxels of the true turns, wobble
    included), shifted out by `shift_hi` voxels above z = 1400, so references there are unseated."""

    def __init__(self, chunk=64, shift_hi=4.0):
        self.chunks = (chunk, chunk, chunk)
        self.shift_hi = shift_hi
        self.reads = 0

    def read(self, idx):
        self.reads += 1
        c = self.chunks[0]
        z, y, x = np.meshgrid(*[np.arange(i * c, (i + 1) * c, dtype=float) for i in idx], indexing="ij")
        r = np.hypot(x - CX, y - CY)
        th = np.mod(np.arctan2(y - CY, x - CX), 2 * math.pi)
        rr = r - wave(z) - np.where(z >= 1400, self.shift_hi, 0.0)
        u = (rr - R0) / PITCH - th / (2 * math.pi)
        dist = np.abs(u - np.round(u)) * PITCH
        return np.where(dist <= 1.5, 255, 0).astype(np.uint8)


def test_rule():
    r = copy.deepcopy(sb.RULE)
    r["seating"]["min_chunk_vertices"] = 4
    r["seating"]["chunks_per_winding"] = 12
    r["seating"]["recto_per_winding"] = 3
    r["controls"]["global_window"] = 24
    r["controls"]["window"] = [20, 40]
    r["split"] = {"tune": ["w105", "w101"], "report": ["w100", "w102"], "note": "synthetic"}
    return r


@unittest.skipIf(np is None, "numpy and scipy are needed")
class SurfbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.rule = test_rule()
        cls.meshes = stack(cls.root)
        cls.refs_dir = cls.root / "refs"
        cls.man = sb.build_manifest(cls.refs_dir, cls.meshes, rule=cls.rule)
        cls.audit = sb.audit(cls.refs_dir, reader=SyntheticPrediction(64), cross_reader=SyntheticPrediction(48),
                             rule=cls.rule, workers=2)
        cls.loaded = sb.load_refs(cls.refs_dir, cls.rule)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ref(self, name):
        return next(r for r in self.loaded[1] if r.name == name)

    def rec(self, name):
        return next(r for r in self.man["references"] if r["name"] == name)

    # ------------------------------------------------------------ rule

    def test_rule_digest_changes_with_any_constant(self):
        self.assertEqual(sb.RULE_DIGEST, sb.rule_digest(sb.RULE))
        for path in (("accept", "bar"), ("distance", "primary_vox"), ("references", "gap_factor"),
                     ("seating", "seated_vox"), ("controls", "neighbour_margin")):
            r = copy.deepcopy(sb.RULE)
            r[path[0]][path[1]] = r[path[0]][path[1]] + 0.01
            self.assertNotEqual(sb.rule_digest(r), sb.RULE_DIGEST, path)

    def test_references_built_under_another_rule_are_refused(self):
        other = copy.deepcopy(self.rule)
        other["references"]["gap_factor"] = 1.7
        with self.assertRaisesRegex(sb.BenchError, "rule"):
            sb.load_refs(self.refs_dir, other)
        other = copy.deepcopy(self.rule)
        other["seating"]["seated_vox"] = 3
        with self.assertRaisesRegex(sb.BenchError, "seating rule"):
            sb.load_refs(self.refs_dir, other)

    def test_the_bar_is_frozen_after_the_references_exist(self):
        # The bar is chosen from controls on built references: changing it changes the score digest but not
        # the references' or the audit's.
        other = copy.deepcopy(self.rule)
        other["accept"]["bar"] = 0.5
        self.assertNotEqual(sb.rule_digest(other), sb.rule_digest(self.rule))
        self.assertEqual(sb.part_digest(other, sb.SEAT_PARTS), sb.part_digest(self.rule, sb.SEAT_PARTS))
        man, refs = sb.load_refs(self.refs_dir, other)
        self.assertEqual(man["digest"], self.man["digest"])

    def test_choose_bar_from_controls(self):
        def site(pos, hard, ramp, moves):
            return {"valid": True, "positive": {"dominant_precision_d4": pos},
                    "planted_hard": {"dominant_precision_d4": hard, "planted_share": 0.5},
                    "planted_ramp": {"dominant_precision_d4": ramp, "planted_share": 0.4},
                    "displaced": {"moves": [{"dominant_precision_d4": m} for m in moves]}}
        r = copy.deepcopy(sb.RULE)
        out = sb.choose_bar([site(1.0, 0.62, 0.7, [0.0, None]), site(0.99, 0.55, 0.5, [0.1])], r)
        self.assertAlmostEqual(out["bar"], 0.8)          # midpoint of 0.7 and 0.99 is 0.845, floored to 0.80
        self.assertEqual((out["lo"], out["hi"]), (0.7, 0.99))
        # negatives too close to the positives: no bar
        out = sb.choose_bar([site(0.97, 0.93, 0.5, [0.0])], r)
        self.assertIsNone(out["bar"])
        self.assertIn("no bar", out["reason"])
        # a planted switch smaller than the planted range does not set the bar
        small = site(1.0, 0.6, 0.5, [0.0])
        small["planted_ramp"].update({"dominant_precision_d4": 0.9, "planted_share": 0.1})
        self.assertEqual(sb.choose_bar([small], r)["lo"], 0.6)
        # a displaced move that left the stack (too little scored) does not set the bar either
        gone = site(1.0, 0.6, 0.5, [0.0])
        gone["displaced"]["moves"].append({"dominant_precision_d4": 0.95, "scored_share_d4": 0.01})
        self.assertEqual(sb.choose_bar([gone], r)["lo"], 0.6)
        # skipped sites do not count; nothing measured gives no bar
        self.assertIsNone(sb.choose_bar([{"valid": None}], r)["bar"])

    def test_edited_audit_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            au = json.loads((self.refs_dir / "audit.json").read_text())
            first = next(iter(au["windings"]))
            au["windings"][first]["seated"] += 1
            (d / "audit.json").write_text(json.dumps(au))
            with self.assertRaisesRegex(sb.BenchError, "digest"):
                sb.load_audit(d, None, self.rule)

    def test_edited_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            man = json.loads((self.refs_dir / "manifest.json").read_text())
            man["chain"][0]["offset_vox"] = 99.0
            (d / "manifest.json").write_text(json.dumps(man))
            with self.assertRaisesRegex(sb.BenchError, "digest"):
                sb.load_manifest(d, self.rule)

    # ------------------------------------------------------------ distances

    def test_point_to_plane_not_nearest_vertex(self):
        yy, xx = np.mgrid[0:20, 0:20].astype(float)
        xyz = np.stack([xx * 20 + 100, yy * 20 + 100, np.full_like(xx, 500.0)], -1)
        ref = sb.Ref("flat", 0, xyz, np.ones(xx.shape, bool))
        pts = np.array([[207.0, 213.0, 501.5], [207.0, 213.0, 497.0], [900.0, 900.0, 500.0]])
        s, inside, _, _ = sb.match(pts, ref)
        self.assertAlmostEqual(abs(s[0]), 1.5, places=6)
        self.assertAlmostEqual(abs(s[1]), 3.0, places=6)
        self.assertEqual(list(inside), [True, True, False])

    def test_a_mesh_that_overlaps_itself_is_matched_to_the_nearer_part(self):
        # 30 columns: 0 to 19 on the plane z = 500, then 20 to 29 traced back over columns 0 to 9, 3 voxels up
        # and a quarter cell along, as a winding traced past its seam onto its own sheet
        yy, cc = np.mgrid[0:12, 0:30].astype(float)
        x = np.where(cc < 20, cc * 20, (cc - 20) * 20 + 5)
        z = np.where(cc < 20, 500.0, 503.0)
        xyz = np.stack([x + 100, yy * 20 + 100, z], -1)
        ref = sb.Ref("fold", 0, xyz, np.ones(cc.shape, bool), self.rule)
        p = np.array([[115.0 + 20 * k, 150.0, 500.0] for k in range(8)])   # on the first part, between its vertices
        s, inside, src, _ = sb.match(p, ref)
        np.testing.assert_allclose(s, 0.0, atol=1e-6)
        self.assertTrue(inside.all())
        one = copy.deepcopy(self.rule)
        one["references"]["match_k"] = 1                                   # the nearest vertex alone: the other part
        s1, _, _, _ = sb.match(p, sb.Ref("fold", 0, xyz, np.ones(cc.shape, bool), one))
        self.assertTrue((np.abs(s1) > 2).any())
        so = sb.self_overlap(ref)
        np.testing.assert_allclose(so[2:10, 1:9], 3.0, atol=1e-6)         # both parts see the other 3 voxels off
        np.testing.assert_allclose(so[2:10, 21:29], 3.0, atol=1e-6)
        self.assertTrue(np.isinf(so[:, 12:18]).all())

    def test_coincident_references_are_no_reference(self):
        # turn 0 ends where turn 1 starts: the shared seam column of both is masked, and the manifest says so
        w105, w101 = self.ref("w105"), self.ref("w101")
        self.assertTrue((w105.label[:, -1] == sb.NOREF).all())
        self.assertTrue((w101.label[:, 0] == sb.NOREF).all())
        self.assertTrue((w105.label[:, 5:-5] == w105.gid).all())
        self.assertGreater(self.rec("w105")["coincident_share"], 0)
        self.assertLess(self.rec("w100")["coincident_share"], 0.02)          # its own seam column only

    def test_upsample_keeps_the_original_vertices(self):
        xyz, valid = winding(1)
        valid[3, 4] = False
        up, uv, src = sb.upsample(xyz, valid, 2)
        self.assertTrue(np.allclose(up[::2, ::2][valid], xyz[valid]))
        self.assertFalse(uv[6, 8])
        self.assertFalse(uv[5, 8] or uv[7, 8] or uv[6, 7])
        self.assertEqual(int(src[7, 9]), 3 * xyz.shape[1] + 4)

    # ------------------------------------------------------------ the manifest

    def test_order_comes_from_geometry_not_names(self):
        order = self.man["order"]
        for a, b in (("w105", "w101"), ("w101", "w103"), ("w103", "w104"), ("w104", "w100"), ("w100", "w102"),
                     ("w102", "w107")):
            self.assertLess(order.index(a), order.index(b), order)
        for c in self.man["chain"]:
            if {c["inner"], c["outer"]} <= {"w105", "w101", "w100", "w102"} and not c["gap"]:
                self.assertAlmostEqual(c["offset_vox"], PITCH, delta=2.0)
                self.assertAlmostEqual(c["step_vox"], PITCH, delta=2.0)     # the step measured directly

    def test_moved_copy_keeps_its_moved_part(self):
        g = next(g for g in self.man["duplicates"] if "w104" in g["members"])
        self.assertEqual(g["kept"], "w103")
        c = g["copies"][0]
        self.assertIn("moved part kept", c["outcome"])
        self.assertAlmostEqual(c["departing_median_offset_vox"], PITCH, delta=1.0)
        r = self.rec("w104")
        self.assertGreater(r["dropped_share"], 0.5)
        self.assertGreater(r["labelled_share"], 0.15)
        self.assertTrue(r["partial"])

    def test_ambiguous_copy_becomes_no_reference(self):
        g = next(g for g in self.man["duplicates"] if "w106" in g["members"])
        self.assertIn("ambiguous", g["copies"][0]["outcome"])
        self.assertGreater(self.rec(g["kept"])["no_reference_share"], 0.05)
        other = "w106" if g["kept"] == "w102" else "w102"
        self.assertEqual(self.rec(other)["labelled_share"], 0.0)

    def test_gap_where_the_copy_did_not_move(self):
        # Turn 3 has a reference only where w104 moved (200 to 300 degrees); elsewhere w103's outer side is a gap.
        r = self.rec("w103")
        self.assertGreater(r["gap_share_outer"], 0.5)
        self.assertLess(r["gap_share_outer"], 0.95)
        self.assertLess(self.rec("w100")["gap_share_outer"], 0.05)
        self.assertGreater(self.rec("w100")["gap_share_inner"], 0.5)     # turn 3 again, seen from outside
        # Without the copy, the chain itself shows the double pitch.
        meshes = {k: v for k, v in self.meshes.items() if k in ("w105", "w101", "w103", "w100", "w102")}
        with tempfile.TemporaryDirectory() as t:
            man = sb.build_manifest(Path(t) / "r", meshes, rule=self.rule)
        gap = [c for c in man["chain"] if c["gap"]]
        self.assertEqual([(c["inner"], c["outer"]) for c in gap], [("w103", "w100")])
        self.assertAlmostEqual(gap[0]["offset_vox"], 2 * PITCH, delta=2.0)

    def test_wide_spacing_to_the_adjacent_winding_is_not_a_gap(self):
        # w101 is pressed 13 voxels in between 120 and 220 degrees, so there it lies 29 voxels (1.8 pitches) inside
        # w103, its adjacent winding: wide, but no winding is missing, so that side is not a gap, and a trace
        # midway between them lies on no winding and is scored off (version 1 masked it as a gap)
        r = self.rec("w101")
        self.assertGreater(r["wide_share_outer"], 0.15)
        self.assertLess(r["gap_share_outer"], 0.02)
        self.assertEqual(r["no_sheet_share_outer"], 0.0)
        xyz, valid = winding(1, math.radians(140), math.radians(200), offset=lambda t, z: 0 * t + 1.5)
        cls, _, _ = self.classes(xyz, valid)
        self.assertGreater((cls == sb.OFF).mean(), 0.9)
        self.assertLess((cls == sb.GAP).mean(), 0.02)

    def test_partial_and_contact(self):
        self.assertTrue(self.rec("w107")["partial"])
        self.assertFalse(self.rec("w101")["partial"])
        self.assertGreater(self.rec("w101")["contact_share"], 0.01)
        self.assertGreater(self.rec("w105")["contact_share"], 0.1)
        A = self.ref("w105")
        contact = A.attrs["contact"] & A.labelled()
        deg = np.degrees(np.arctan2(A.xyz[..., 1] - CY, A.xyz[..., 0] - CX)) % 360
        inside = contact & (deg > 115) & (deg < 225)
        self.assertGreater(inside.sum() / contact.sum(), 0.8)    # the bulge, and a little at the spiral seam

    # ------------------------------------------------------------ scoring

    def classes(self, xyz, valid, d=4.0):
        refs = sb.near_refs(xyz[valid], self.loaded[1])
        S, IN, J = sb._matches(xyz[valid], refs, 2)
        cls, lab, _, _ = sb._classify(S, IN, J, refs, self.rule, d, None)
        return cls, lab, refs

    def test_gap_is_unscored_and_between_windings_is_off(self):
        xyz, valid = winding(3, math.radians(40), math.radians(120))   # the missing turn, away from the moved part
        cls, _, _ = self.classes(xyz, valid)
        self.assertGreater((cls == sb.GAP).mean(), 0.9)
        xyz, valid = winding(4, math.radians(30), math.radians(90), offset=lambda t, z: 0 * t + 8.0)
        cls, _, _ = self.classes(xyz, valid)
        self.assertGreater((cls == sb.OFF).mean(), 0.9)
        xyz, valid = winding(3, math.radians(220), math.radians(280))  # where the moved part is the reference
        cls, lab, _ = self.classes(xyz, valid)
        self.assertGreater((lab == self.ref("w104").gid).mean(), 0.9)

    def test_switch_edges_and_seam_crossings(self):
        a, va = winding(4, math.radians(30), math.radians(90), ncol=20)
        b, _ = winding(5, math.radians(30), math.radians(90), ncol=20)
        W = a.shape[1]
        hard = np.concatenate([a[:, :W // 2], b[:, W // 2:]], 1)
        refs = sb.near_refs(hard[va], self.loaded[1])
        e = sb.evaluate(hard, va, refs, self.rule, "control")
        self.assertEqual(e["switches"]["switch_edges"], a.shape[0])
        self.assertEqual(e["switches"]["rows_with_switch"], a.shape[0])
        self.assertEqual(e["switches"]["boundary_edges"], 0)
        self.assertLess(e["d4"]["dominant_precision"], 0.6)
        self.assertFalse(e["accepted"])
        # a trace that follows the spiral across the seam from turn 0 into turn 1 changes label without a switch
        th = np.linspace(2 * math.pi - 0.5, 2 * math.pi + 0.5, 50)
        z = np.arange(1100.0, 1400.0, STEP)
        T, Z = np.meshgrid(th, z)
        r = spiral_r(T) + wave(Z)
        seam = np.stack([CX + r * np.cos(T), CY + r * np.sin(T), Z], -1)
        sv = np.ones(T.shape, bool)
        e = sb.evaluate(seam, sv, sb.near_refs(seam[sv], self.loaded[1]), self.rule, "control")
        self.assertEqual(e["switches"]["switch_crossings"], 0)
        # where the two turns meet they coincide: those vertices are no-reference, so the change is bridged
        self.assertGreater(e["switches"]["boundary_edges"] + e["switches"]["bridged_boundaries"], 0)

    def test_contact_switch_is_counted_separately(self):
        # w101 is pressed to 3 voxels from w105 between 120 and 220 degrees: a ramp there switches in contact
        rows = np.arange(1100.0, 1401.0, STEP)
        t0, t1 = math.radians(140), math.radians(200)
        a, va = winding(0, t0, t1, rows=rows, ncol=24)
        b, _ = winding(1, t0, t1, offset=bump(), rows=rows, ncol=24)
        W = a.shape[1]
        w = np.clip((np.arange(W) - W / 2 + 2) / 4, 0, 1)[None, :, None]
        ramp = a + w * (b - a)
        e = sb.evaluate(ramp, va, sb.near_refs(ramp[va], self.loaded[1]), self.rule, "control")
        self.assertGreaterEqual(e["switches"]["rows_with_switch"], len(rows) // 2)
        self.assertGreater(e["switches"]["switch_edges_contact"] + e["switches"]["bridged_switches_contact"], 0)

    # ------------------------------------------------------------ seating

    def test_audit_marks_offset_regions_unseated(self):
        w = self.audit["windings"]["w100"]
        self.assertGreater(w["sampled"], 3)
        self.assertLessEqual(w["chosen"], self.rule["seating"]["chunks_per_winding"])
        self.assertLessEqual(self.audit["chunks_sampled"],
                             self.rule["seating"]["chunks_per_winding"] * len(self.audit["windings"]))
        for key, reg in w["regions"].items():
            z = int(key.split("_")[0]) * 64
            want = "unseated" if z >= 1400 else "seated"
            if z + 64 > 1400 > z:
                continue
            self.assertEqual(reg["status"], want, (key, reg))
        self.assertGreater(self.audit["summary"]["cross_compared"], 0)
        self.assertEqual(self.audit["summary"]["cross_agrees"], self.audit["summary"]["cross_compared"])
        r = self.ref("w100")
        self.assertTrue((r.seat == sb.SEAT_OFF).any() and (r.seat == sb.SEATED).any())

    def test_unseated_region_is_excluded(self):
        r = self.ref("w100")
        hi = r.labelled() & (r.seat == sb.SEAT_OFF)
        rows = np.flatnonzero(hi.any(1))
        cols = np.flatnonzero(hi.any(0))
        xyz = r.xyz[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
        valid = hi[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
        e = sb.evaluate(xyz, valid, sb.near_refs(xyz[valid], self.loaded[1]), self.rule, "full")
        self.assertGreater(e["d4"]["unscored"].get("unseated", 0), 0.9)
        self.assertEqual(e["d2"]["scored"], 0)

    # ------------------------------------------------------------ controls

    def site(self, name, size=24):
        A = self.ref(name)
        lab = A.labelled()
        H, W = lab.shape
        return A, sb._box_around(A, (H // 2, W // 6), size)

    def test_controls_pass_at_a_clean_site(self):
        man, refs = self.loaded
        A, box = self.site("w100")
        res = sb.site_controls(refs, man, A, box, self.rule)
        self.assertTrue(res["valid"], res["failed"])
        steps = [s["precision_d2"] for s in res["offset_sweep"]["steps"]]
        self.assertGreater(steps[0], 0.95)
        self.assertTrue(0.3 <= steps[1] <= 0.7, steps)
        self.assertLess(steps[2], 0.05)
        self.assertLess(res["planted_hard"]["dominant_precision_d4"], 0.7)

    def test_controls_fail_when_what_they_guard_is_broken(self):
        man, refs = self.loaded
        A, box = self.site("w100")
        # a nearest-vertex distance in place of point to plane: the offset sweep fails
        real = sb.match

        def nearest_vertex(P, ref, workers=2):
            s, ins, src, nb = real(P, ref, workers)
            pts = ref.scoring()[0]
            d, j = ref.tree().query(np.asarray(P, float))
            return np.where(np.isfinite(d), d, np.nan), ins, src, nb

        with mock.patch.object(sb, "match", nearest_vertex):
            res = sb.site_controls(refs, man, A, box, self.rule)
        self.assertFalse(res["offset_sweep"]["pass"])
        self.assertIn("offset_sweep", res["failed"])
        # a tolerance beyond d and a zero displacement: those controls fail
        r = copy.deepcopy(self.rule)
        r["controls"]["tolerance_vox"] = 6.0
        r["controls"]["displace_z_vox"] = [0.0]
        res = sb.site_controls(refs, man, A, box, r)
        self.assertFalse(res["tolerance"]["accepted"])
        self.assertTrue(res["valid"] or "tolerance" not in res["failed"])
        self.assertFalse(res["displaced"]["pass"])
        # a labeller that cannot tell the windings apart: the neighbour gets the site's label everywhere
        B = next(x for x in refs if x.name == "w102")
        A_ = next(x for x in refs if x.name == "w100")
        saved = B.label.copy()
        try:
            B.label = np.where(saved == B.gid, A_.gid, saved).astype(np.int32)
            B.reset()
            res = sb.site_controls(refs, man, A, box, self.rule)
        finally:
            B.label = saved
            B.reset()
        for k in ("planted_hard", "neighbour"):
            self.assertFalse(res[k]["pass"], (k, res[k]))
        # a labeller that gives every other vertex the neighbour's id: the positive control fails
        real_classify = sb._classify

        def scrambled(S, IN, J, refs_, rule, d, seat_mode=None, masks=True):
            cls, lab, best, bestd = real_classify(S, IN, J, refs_, rule, d, seat_mode, masks)
            lab = lab.copy()
            lab[::2] = np.where(lab[::2] == A_.gid, B.gid, lab[::2])
            return cls, lab, best, bestd

        with mock.patch.object(sb, "_classify", scrambled):
            res = sb.site_controls(refs, man, A_, box, self.rule)
        self.assertFalse(res["positive"]["pass"])

    def test_drift_control_fails_when_a_mask_hides_off_sheet_vertices(self):
        man, refs = self.loaded
        A, box = self.site("w100")
        res = sb.site_controls(refs, man, A, box, self.rule)
        d = res["planted_drift"]
        self.assertTrue(d["pass"], d)
        self.assertGreater(d["moved_off_share"], 0.95)
        self.assertTrue(d["share_in_range"])
        self.assertFalse(d["accepted"])
        # a gap mask that swallows every vertex off a winding (as version 1's did over a third of each winding's
        # flanks on PHerc0139): the drift is no longer counted against the window, and the site is invalid
        real = sb._classify

        def gap_everywhere(S, IN, J, refs_, rule, d, seat_mode=None, masks=True):
            cls, lab, best, bestd = real(S, IN, J, refs_, rule, d, seat_mode, masks)
            cls = cls.copy()
            cls[cls == sb.OFF] = sb.GAP
            return cls, lab, best, bestd

        with mock.patch.object(sb, "_classify", gap_everywhere):
            res = sb.site_controls(refs, man, A, box, self.rule)
        self.assertFalse(res["planted_drift"]["pass"], res["planted_drift"])
        self.assertFalse(res["valid"])
        self.assertIn("planted_drift", res["failed"])

    def test_planted_switches_fail_when_switches_are_missed(self):
        man, refs = self.loaded
        real = sb._crossings

        def blind(*a, **k):
            out = real(*a, **k)
            for key in ("switch_edges", "switch_edges_contact", "bridged_switches", "bridged_switches_contact",
                        "switch_crossings", "rows_with_switch"):
                out[key] = 0
            return out

        A, box = self.site("w100")
        with mock.patch.object(sb, "_crossings", blind):
            res = sb.site_controls(refs, man, A, box, self.rule)
        self.assertTrue(res["positive"]["pass"])
        self.assertFalse(res["planted_hard"]["pass"])
        self.assertFalse(res["planted_ramp"]["pass"])
        self.assertFalse(res["valid"])

    def test_displaced_moves_are_scored_against_the_references_where_they_land(self):
        man, refs = self.loaded
        A, box = self.site("w100")
        xyz, valid, _ = sb._window(A, box)
        seen = []
        real = sb.near_refs

        def spy(points, refs_):
            seen.append(float(np.median(np.asarray(points)[:, 2])))
            return real(points, refs_)

        with mock.patch.object(sb, "near_refs", spy):
            sb.site_controls(refs, man, A, box, self.rule)
        z0 = float(np.median(xyz[valid][:, 2]))
        for dz in self.rule["controls"]["displace_z_vox"]:
            self.assertTrue(any(abs(abs(z - z0) - dz) < 1e-6 for z in seen), (dz, seen))

    def test_ramp_control_fails_when_the_switch_is_missed(self):
        man, refs = self.loaded
        A = self.ref("w105")
        a = A.attrs
        B = self.ref("w101")
        hit = A.labelled() & (((a["lab_pos"] == B.gid) & (a["g_pos"] <= 8)) | ((a["lab_neg"] == B.gid) & (a["g_neg"] <= 8)))
        self.assertTrue(hit.any())
        deg = np.degrees(np.arctan2(A.xyz[..., 1] - CY, A.xyz[..., 0] - CX)) % 360
        rc = np.argwhere(hit & (np.abs(deg - 170) < 20))
        box = sb._box_around(A, tuple(rc[len(rc) // 2]), 24)
        res = sb.site_controls(refs, man, A, box, self.rule)
        self.assertTrue(res["planted_ramp"]["pass"], res["planted_ramp"])
        self.assertTrue(res["planted_ramp"]["in_contact_zone"])
        r = copy.deepcopy(self.rule)
        r["controls"]["planted_row_share"] = 2.0        # asks for more switch rows than there are: must fail
        res = sb.site_controls(refs, man, A, box, r)
        self.assertFalse(res["planted_ramp"]["pass"])

    def test_per_pair_neighbour_bar(self):
        man, refs = self.loaded
        pairs = sb.pair_controls(refs, man, self.rule)
        self.assertTrue(pairs)
        self.assertTrue(all(p["pass"] for p in pairs), [p for p in pairs if not p["pass"]])
        bulge = [p for p in pairs if {p["winding"], p["against"]} == {"w105", "w101"}]
        self.assertTrue(bulge)
        # the bulging pair touches over more than 5 %: a fixed 0.05 bar would fail it, the per-pair bar does not
        self.assertTrue(any(p["share_within_d4"] > 0.05 for p in bulge), bulge)
        for p in bulge:
            self.assertAlmostEqual(p["bar"], (p["contact_share"] or 0) + self.rule["controls"]["neighbour_margin"],
                                   places=3)

    def test_pair_check_fails_when_the_matching_differs_from_the_manifest(self):
        man, refs = self.loaded
        real = sb.match

        def shrunk(P, ref, workers=2):                    # offsets a quarter of their size: a unit error
            s, ins, src, nb = real(P, ref, workers)
            return s * 0.25, ins, src, nb

        with mock.patch.object(sb, "match", shrunk):
            pairs = sb.pair_controls(refs, man, self.rule)
        self.assertTrue(any(not p["pass"] for p in pairs))
        stub = mock.patch.object(sb, "site_controls", lambda *a, **k: {"valid": True, "failed": []})
        with stub:
            self.assertTrue(sb.run_controls(self.refs_dir, self.rule)["valid"])
        with stub, mock.patch.object(sb, "match", shrunk):
            out = sb.run_controls(self.refs_dir, self.rule)
        self.assertFalse(out["valid"])
        self.assertLess(out["summary"]["pairs"]["pass"], out["summary"]["pairs"]["of"])

    def test_score_is_invalid_without_an_audit_or_with_failed_controls(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            xyz, valid = winding(4, math.radians(20), math.radians(100), rows=np.arange(1000.0, 1361.0, STEP),
                                 ncol=28)
            sb.write_tifxyz(t / "good", xyz, valid)
            bare = t / "refs"
            bare.mkdir()
            (bare / "manifest.json").write_text((self.refs_dir / "manifest.json").read_text())
            (bare / "attrs").mkdir()
            for f in (self.refs_dir / "attrs").iterdir():
                (bare / "attrs" / f.name).write_bytes(f.read_bytes())
            res = sb.score(t / "good", bare, selfcross=False, rule=self.rule)
            self.assertEqual(res["verdict"], "invalid")
            self.assertTrue(any("audit" in r for r in res["invalid_reasons"]), res["invalid_reasons"])
            # the full references, but a nearest-vertex distance: the offset sweep at the site fails
            real = sb.match

            def nearest_vertex(P, ref, workers=2):
                s, ins, src, nb = real(P, ref, workers)
                d, _ = ref.tree().query(np.asarray(P, float))
                return np.where(np.isfinite(d), d, np.nan), ins, src, nb

            with mock.patch.object(sb, "match", nearest_vertex):
                res = sb.score(t / "good", self.refs_dir, selfcross=False, rule=self.rule)
            self.assertEqual(res["verdict"], "invalid")
            self.assertIn("offset_sweep", res["controls"]["failed"])

    def test_control_site_lies_on_the_candidate(self):
        # a candidate covering both ends of a winding whose middle is masked: a window on the middle of its
        # bounding box would hold no labelled vertex, so the site goes on a vertex the candidate covers
        xyz, valid = winding(4, 0.0, math.radians(120), ncol=60)
        lab = np.full(valid.shape, 7, np.int32)
        lab[:, 8:52] = sb.NOREF
        A = sb.Ref("wA", 7, xyz, valid, self.rule, label=lab)
        rows, cols = np.mgrid[0:valid.shape[0], 0:valid.shape[1]]
        js = (rows * valid.shape[1] + cols)[(cols < 6) | (cols >= 54)]
        n = js.size
        internal = {"d4": (np.full(n, sb.ON, np.int8), np.full(n, 7), np.zeros(n, np.int64)), "J": js[None, :]}
        got, box = sb._site_for({"dominant_id": 7}, internal, [A], [A], self.rule)
        self.assertIs(got, A)
        self.assertGreaterEqual(int(A.labelled()[box[0]:box[1], box[2]:box[3]].sum()), 50)

    def test_run_controls_and_score(self):
        out = sb.run_controls(self.refs_dir, self.rule, names=["w100", "w102", "w101"])
        self.assertTrue(out["valid"], json.dumps(out["summary"]))
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            xyz, valid = winding(4, math.radians(20), math.radians(100), rows=np.arange(1000.0, 1361.0, STEP),
                                 ncol=28)
            sb.write_tifxyz(t / "good", xyz, valid)
            res = sb.score(t / "good", self.refs_dir, selfcross=False, rule=self.rule)
            self.assertTrue(res["valid"], res["invalid_reasons"])
            self.assertEqual(res["verdict"], "one winding")
            self.assertEqual(res["metrics"]["dominant"], "w100")
            self.assertGreater(res["metrics"]["recall_d4"], 0.1)
            self.assertEqual(res["metrics"]["switches"]["switch_crossings"], 0)
            b, _ = winding(5, math.radians(20), math.radians(100), rows=np.arange(1000.0, 1361.0, STEP), ncol=28)
            W = xyz.shape[1]
            sb.write_tifxyz(t / "switch", np.concatenate([xyz[:, :W // 2], b[:, W // 2:]], 1), valid)
            res = sb.score(t / "switch", self.refs_dir, selfcross=False, rule=self.rule)
            self.assertEqual(res["verdict"], "not one winding", res["invalid_reasons"])
            self.assertGreater(res["metrics"]["switches"]["switch_edges"], 0)
            res = sb.score(t / "good", self.refs_dir, selfcross=False, rule=self.rule, controls=False)
            self.assertEqual(res["verdict"], "invalid")
            far = xyz + np.array([0.0, 0.0, 5000.0])
            sb.write_tifxyz(t / "far", far, valid)
            res = sb.score(t / "far", self.refs_dir, selfcross=False, rule=self.rule)
            self.assertEqual(res["verdict"], "not scorable")

    # ------------------------------------------------------------ listing

    def test_find_meshes_from_a_listing(self):
        def page(prefixes):
            return ("<ListBucketResult>" + "".join(f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>"
                                                    for p in prefixes) + "</ListBucketResult>").encode()

        seg = "PHerc0139/segments/"
        listing = {
            seg: [seg + "20260126000000-w045_2026012619/", seg + "20260130000001-w030_202601301912/",
                  seg + "20260422000000-title_2026042222_zmid_flatboi/"],
            seg + "20260126000000-w045_2026012619/mesh/": [
                seg + "20260126000000-w045_2026012619/mesh/20260126000000-on-20250728140407-9.362um.tifxyz/",
                seg + "20260126000000-w045_2026012619/mesh/20260126000000-on-20260102150214-2.399um.tifxyz/"],
            seg + "20260130000001-w030_202601301912/mesh/": [
                seg + "20260130000001-w030_202601301912/mesh/intermediate/"],
        }

        class Resp:
            def __init__(self, body):
                self.body = body

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(url, timeout=60):
            from urllib.parse import parse_qs, urlparse
            prefix = parse_qs(urlparse(url).query)["prefix"][0]
            return Resp(page(listing.get(prefix, [])))

        found, skipped = sb.find_meshes(opener)
        self.assertEqual([f["name"] for f in found], ["w045"])
        self.assertTrue(found[0]["prefix"].endswith("20260126000000-on-20250728140407-9.362um.tifxyz"))
        self.assertEqual(len(skipped), 2)


# ---------------------------------------------------------------- predscore (stage 4: surface prediction)

# Turn 2 pressed 10 voxels in between 60 and 150 degrees (6 voxels from turn 1: counted lines), turn 3 pressed 12.5
# in between 200 and 280 degrees (3.5 voxels from turn 2: the 3 to 4 stratum).
PRESSES = {2: (60.0, 150.0, 10.0), 3: (200.0, 280.0, 12.5)}
PRED_ROWS = (1000.0, 1241.0)
M7_SHAPE = [20974, 6621, 6621]


def press(k):
    return bump(*PRESSES[k]) if k in PRESSES else None


def pred_stack(root):
    """Turns 0 to 4 as tune windings w301 to w305 over z 1000 to 1240, and w306, turn 5 from 80 to 140 degrees
    (outside the counted contact), the report winding."""
    rows = np.arange(*PRED_ROWS, STEP)
    meshes = {f"w{301 + k}": winding(k, offset=press(k), rows=rows) for k in range(5)}
    meshes["w306"] = winding(5, math.radians(80), math.radians(140), rows=rows)
    return {name: sb.write_tifxyz(Path(root) / "meshes" / name, *m) for name, m in meshes.items()}


def turn_radii(z, y, x, turns=range(0, 7)):
    """(radius of each turn's sheet at the voxels' angle and z, the voxels' radius), presses included."""
    r = np.hypot(x - CX, y - CY)
    phi = np.mod(np.arctan2(y - CY, x - CX), 2 * math.pi)
    rk = []
    for k in turns:
        rr = R0 + PITCH * (phi / (2 * math.pi) + k) + wave(z)
        if k in PRESSES:
            rr = rr + press(k)(phi, z)
        rk.append(rr)
    return np.stack(rk), r


def grid(idx, c):
    return np.meshgrid(*[np.arange(i * c, (i + 1) * c, dtype=float) for i in idx], indexing="ij")


class SheetMap:
    """A synthetic surface prediction: 255 within `half` voxels (radially) of every turn; with `fill`, also between
    two adjacent turns wherever they lie under 9 voxels apart (touching sheets merged); with `cut`, nothing within 1
    voxel of the midway radius of two such turns (touching sheets parted); with `broken`, turn `broken`'s sheet cut
    into small pieces (every 4th plane along each axis cleared on it); `missing` chunks read as None."""

    def __init__(self, chunk=96, half=1.5, fill=False, cut=False, missing=(), broken=None, value=255):
        self.chunks = (chunk,) * 3
        self.half, self.fill, self.cut, self.missing = half, fill, cut, set(missing)
        self.broken, self.value = broken, value
        self.reads = 0

    def read(self, idx):
        if tuple(int(i) for i in idx) in self.missing:
            return None
        self.reads += 1
        z, y, x = grid(idx, self.chunks[0])
        rk, r = turn_radii(z, y, x)
        on = np.abs(r[None] - rk).min(0) <= self.half
        if self.fill:
            for a, b in zip(rk[:-1], rk[1:]):
                on |= (r >= a) & (r <= b) & (b - a < 9)
        if self.cut:
            for a, b in zip(rk[:-1], rk[1:]):
                on &= ~((np.abs(r - (a + b) / 2) <= 1.0) & (b - a < 9))
        if self.broken is not None:
            planes = (np.mod(z, 4) == 0) | (np.mod(y, 4) == 0) | (np.mod(x, 4) == 0)
            on &= ~((np.abs(r - rk[self.broken]) <= self.half + 0.5) & planes)
        return np.where(on, self.value, 0).astype(np.uint8)


class Offset:
    """A reader whose voxel 0 sits at `offset` in the frame (the content moved by `offset`)."""

    def __init__(self, base, offset):
        self.base, self.offset, self.chunks = base, tuple(offset), base.chunks

    def read(self, idx):
        return self.base.read(idx)


class InBox:
    """A map released for a box only: the base map inside the box, 0 outside it."""

    def __init__(self, base, box):
        self.base, self.box, self.chunks = base, np.asarray(box).reshape(3, 2), base.chunks

    def read(self, idx):
        arr = self.base.read(idx)
        z, y, x = grid(idx, self.chunks[0])
        inside = ((z >= self.box[0, 0]) & (z < self.box[0, 1]) & (y >= self.box[1, 0]) & (y < self.box[1, 1])
                  & (x >= self.box[2, 0]) & (x < self.box[2, 1]))
        return np.where(inside, arr, 0).astype(np.uint8)


class Eroded:
    """The base map eroded by one voxel (6-connected): sheets thinned from both faces, nothing parted."""

    def __init__(self, base):
        self.base, self.chunks = base, base.chunks

    def read(self, idx):
        from scipy import ndimage
        on = self.base.read(idx) >= 128
        return np.where(ndimage.binary_erosion(on, ndimage.generate_binary_structure(3, 1)), 255, 0).astype(np.uint8)


class SyntheticCT:
    """CT: 0 outside the scroll (and from z = zero_from up, when given), 200 on the sheets, 60 between them."""

    def __init__(self, chunk=64, zero_from=None):
        self.chunks = (chunk,) * 3
        self.zero_from = zero_from

    def read(self, idx):
        z, y, x = grid(idx, self.chunks[0])
        rk, r = turn_radii(z, y, x)
        v = np.where(np.abs(r[None] - rk).min(0) <= 1.5, 200, 60)
        v = np.where(r > R0 + 8 * PITCH, 0, v)
        if self.zero_from is not None:
            v = np.where(z >= self.zero_from, 0, v)
        return v.astype(np.uint8)


def write_zarr(root, reader, keys, chunk=96, shape=None, dtype="|u1", fill_value=0, cast=None):
    """A local zarr v2 array (no compression, '/' separator) holding `reader`'s chunks `keys`."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".zarray").write_text(json.dumps({"chunks": [chunk] * 3, "dtype": dtype, "compressor": None,
                                              "shape": shape or M7_SHAPE, "dimension_separator": "/",
                                              "order": "C", "fill_value": fill_value, "zarr_format": 2,
                                              "filters": None}))
    for k in keys:
        arr = reader.read(k)
        if cast is not None:
            arr = cast(arr)
        f = root / "/".join(str(int(v)) for v in k)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(np.ascontiguousarray(arr).tobytes())
    return root


def pred_test_rule():
    r = copy.deepcopy(sb.RULE)
    r["seating"]["min_chunk_vertices"] = 4
    r["split"] = {"tune": [f"w{n}" for n in range(301, 306)], "report": ["w306"], "note": "synthetic"}
    return r


def pred_test_prule(version=2):
    p = copy.deepcopy(sb.PRED_RULES[version])
    p["chunk"] = 96
    p["sample"].update({"dev_chunks": 10, "report_chunks": 10, "min_lines": 3})
    p["bootstrap"]["resamples"] = 400
    return p


@unittest.skipIf(np is None, "numpy and scipy are needed")
class PredscoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.rule, cls.prule, cls.prule1 = pred_test_rule(), pred_test_prule(), pred_test_prule(1)
        cls.refs_dir = cls.root / "refs"
        cls.man = sb.build_manifest(cls.refs_dir, pred_stack(cls.root), rule=cls.rule)
        cls.loaded = sb.load_refs(cls.refs_dir, cls.rule)
        cls.good = cls.score_map(SheetMap(cut=True), controls=True)      # touching sheets parted everywhere
        cls.plain = cls.score_map(SheetMap(), controls=True)             # merged only where they are 3.5 apart
        cls.merged = cls.score_map(SheetMap(fill=True), controls=True)   # merged wherever under 9 apart

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def score_map(cls, m7, controls=False, ct=None, prule=None, pred="m7", against=None, **kw):
        # m7copy is the A/A control's second reader: an independent instance of the same map
        readers = {"m7": m7, "m7copy": copy.deepcopy(m7), "recto090": SheetMap(half=2.5), "ct": ct or SyntheticCT()}
        readers.update(kw.pop("readers", {}))
        return sb.predscore(pred, against, "dev", controls, cls.refs_dir, rule=cls.rule, prule=prule or cls.prule,
                            readers=readers, workers=2, **kw)

    def gid(self, name):
        return next(r.gid for r in self.loaded[1] if r.name == name)

    def chunks_of(self, res):
        return [c for c in res["per_chunk"] if "arms" in c]

    def busiest(self):
        """(chunk key, its box) of the sampled chunk with the most counted lines."""
        c = max(self.chunks_of(self.good), key=lambda c: c["lines"])
        k = tuple(int(v) for v in c["chunk"].split("_"))
        return k, [v for i in k for v in (i * 96, i * 96 + 96)]

    # ------------------------------------------------------------ rule versions

    def test_rule_version_1_is_kept_and_version_2_differs(self):
        self.assertEqual(sb.digest(sb.PRED_RULE_V1), "08e11933de66233b94aa76d7ae7807873dd663993fcc6cb75dd64ca8a517d69b")
        self.assertEqual(sb.PRED_RULE["version"], 2)
        self.assertNotEqual(sb.digest(sb.PRED_RULE), sb.digest(sb.PRED_RULE_V1))
        self.assertEqual(sb.PRED_RULES[1], sb.PRED_RULE_V1)
        # version 1 under the same maps: the old two-sided band, A-only G4 and the absolute displaced drop
        v1 = self.score_map(SheetMap(cut=True), controls=True, prule=self.prule1)
        self.assertEqual(v1["pred_rule_version"], 1)
        self.assertNotIn("m7copy", v1["arms"])
        self.assertIn("drop", v1["controls"]["displaced"])
        self.assertNotIn("ratio", v1["controls"]["displaced"])
        self.assertNotIn("scorer_sha256", v1["run_rule"])

    def test_run_rule_holds_the_scorer_sha256(self):
        man, refs = self.loaded
        rr = sb.pred_run_rule("dev", [1, 2], man, self.rule, self.prule)
        self.assertEqual(rr["scorer_sha256"], sb._sha256(Path(sb.__file__)))
        other = dict(rr, scorer_sha256="0" * 64)
        self.assertNotEqual(sb.digest(rr), sb.digest(other))

    # ------------------------------------------------------------ lines and sample

    def test_lines_are_counted_once_from_the_inner_winding(self):
        man, refs = self.loaded
        L = sb._pred_lines(refs, man, self.prule)
        main, strat = L["main"], ~L["main"]
        self.assertGreater(main.sum(), 50)
        self.assertGreater(strat.sum(), 20)
        # the counted contact is turn 1 with the pressed turn 2 at about 6 voxels (plus the flanks of the 3.5 voxel
        # press, which pass through 5 to 8), always seen from the inner winding of the two
        self.assertEqual(set(L["a"][main].tolist()), {self.gid("w302"), self.gid("w303")})
        self.assertTrue((L["b"] == L["a"] + 1).all())                   # ids follow names, inner to outer here
        fully = main & (L["a"] == self.gid("w302")) & (np.abs(L["g"] - 6.0) < 1.0)
        self.assertGreater(fully.sum() / main.sum(), 0.5)
        self.assertTrue(((L["g"][main] >= 5) & (L["g"][main] <= 8)).all())
        # the 3.5 voxel contact of turns 2 and 3 is the stratum, again from the inner winding
        self.assertIn(self.gid("w303"), set(L["a"][strat].tolist()))
        self.assertNotIn(self.gid("w304"), set(L["a"].tolist()))
        self.assertTrue(((L["g"][strat] >= 3) & (L["g"][strat] < 5)).all())

    def test_sample_is_seeded_excludes_report_chunks_and_enters_the_digest(self):
        man, refs = self.loaded
        a, n = sb.pred_sample(refs, man, "dev", self.rule, self.prule)
        b, _ = sb.pred_sample(refs, man, "dev", self.rule, self.prule)
        self.assertEqual(a, b)
        self.assertEqual(len(a), min(self.prule["sample"]["dev_chunks"], n))
        self.assertTrue(a)
        # no sampled chunk holds a point of the report winding w306
        w306 = next(r for r in refs if r.name == "w306")
        bad = set(sb._enc(np.floor_divide(w306.xyz[w306.valid][:, ::-1], 96).astype(np.int64)).tolist())
        every = dict(self.prule, sample=dict(self.prule["sample"], dev_chunks=10 ** 6))
        allc, _ = sb.pred_sample(refs, man, "dev", self.rule, every)
        self.assertFalse(bad & set(allc))
        noex = copy.deepcopy(self.rule)
        noex["split"]["report"] = []
        wider, _ = sb.pred_sample(refs, man, "dev", noex, every)
        self.assertTrue(bad & set(wider), "the synthetic report winding shares no chunk with a counted line")
        # another seed draws another sample, and the run rule's digest follows the chunks
        other = copy.deepcopy(self.prule)
        other["sample"]["seed"] = 1
        other["sample"]["dev_chunks"] = 3
        c, _ = sb.pred_sample(refs, man, "dev", self.rule, other)
        d3 = copy.deepcopy(self.prule)
        d3["sample"]["dev_chunks"] = 3
        e, _ = sb.pred_sample(refs, man, "dev", self.rule, d3)
        self.assertNotEqual(c, e)
        r1 = sb.digest(sb.pred_run_rule("dev", c, man, self.rule, other))
        r2 = sb.digest(sb.pred_run_rule("dev", e, man, self.rule, other))
        self.assertNotEqual(r1, r2)

    def test_report_run_needs_the_frozen_digest(self):
        info = self.score_map(SheetMap(), rule_only=True)
        self.assertIn("run_rule", info)
        self.assertEqual(info["run_rule_digest"], sb.digest(info["run_rule"]))
        rep = sb.predscore("m7", split="report", refs_dir=self.refs_dir, rule=self.rule, prule=self.prule,
                           rule_only=True)
        with self.assertRaisesRegex(sb.BenchError, "frozen"):
            sb.predscore("m7", split="report", refs_dir=self.refs_dir, rule=self.rule, prule=self.prule,
                         readers={"m7": SheetMap(), "recto090": SheetMap(), "ct": SyntheticCT()})
        with self.assertRaisesRegex(sb.BenchError, "frozen"):
            sb.predscore("m7", split="report", refs_dir=self.refs_dir, rule=self.rule, prule=self.prule,
                         frozen="0" * 64, readers={"m7": SheetMap(), "recto090": SheetMap(), "ct": SyntheticCT()})
        self.assertNotEqual(rep["run_rule_digest"], info["run_rule_digest"])

    def test_windows_are_voxel_disjoint_in_version_2(self):
        man, refs = self.loaded
        L = sb._pred_lines(refs, man, self.prule)
        k, _ = self.busiest()
        origin = np.array(k) * 96
        ct, _ = sb._read_block(SyntheticCT(), origin, 96)
        _, codes, inside = sb._place(L["p"], L["n"], L["g"], self.prule)
        sel = (codes == int(sb._enc(np.array(k)))) & inside
        args = (L["p"][sel] - origin, L["n"][sel], L["g"][sel], L["a"][sel], L["main"][sel])
        v2 = sb._Lines(*args, self.prule, ct, b=L["b"][sel])
        v1 = sb._Lines(*args, self.prule1, ct, b=L["b"][sel])
        self.assertGreater(len(v2), 10)
        self.assertTrue(all(not (set(a.tolist()) & set(b.tolist())) for a, b in zip(v2.fa, v2.fb)))
        # version 1 split on the sample parameter, so a voxel near the midpoint sat in both windows
        self.assertTrue(any(set(a.tolist()) & set(b.tolist()) for a, b in zip(v1.fa, v1.fb)))
        # each voxel goes to the side its own position is on
        for i in range(len(v2)):
            proj = ((v2.S[i] - v2.P[i]) * v2.N[i]).sum(-1)
            self.assertTrue((proj[v2.a_win[i]] < v2.g[i] / 2).all())
            self.assertTrue((proj[v2.b_win[i]] >= v2.g[i] / 2).all())

    # ------------------------------------------------------------ the metric

    def test_separated_sheets_are_clean_and_merged_ones_are_not(self):
        g, m = self.good["summary"]["m7"], self.merged["summary"]["m7"]
        self.assertGreater(self.good["lines"], 30)
        self.assertGreater(g["cs"]["value"], 0.9)
        self.assertLess(m["cs"]["value"], 0.1)
        # both maps have both sheets on: what differs is the component test alone
        self.assertGreater(m["a_on"]["value"], 0.9)
        self.assertGreater(m["b_on"]["value"], 0.9)
        self.assertEqual(self.good["lines"], self.merged["lines"])
        self.assertGreater(g["g1_seated"]["value"], 0.9)
        self.assertGreater(g["g4_continuity"]["value"], 0.9)

    def test_bootstrap_is_seeded_and_identity_collapses(self):
        again = self.score_map(SheetMap(cut=True), controls=False, against="m7")
        self.assertEqual(again["summary"]["m7"]["cs"], self.good["summary"]["m7"]["cs"])
        ident = self.good["controls"]["identity"]
        self.assertTrue(ident["pass"])
        self.assertEqual(ident["arm"], "m7copy")
        self.assertEqual(ident["cs"]["diff"], 0.0)
        self.assertEqual(ident["cs"]["ci"], [0.0, 0.0])

    def test_identity_check_fails_when_the_arms_differ(self):
        chunks = self.chunks_of(self.merged)
        self.assertTrue(sb._identity_ok(sb.pred_compare(chunks, "m7", "m7", self.prule)))
        self.assertFalse(sb._identity_ok(sb.pred_compare(chunks, "m7:oracle", "m7", self.prule)))

    def test_the_a_a_control_reads_m7_again_and_fails_when_the_second_reader_differs(self):
        # a second reader that does not reproduce m7 (thicker sheets) makes the run invalid
        res = self.score_map(SheetMap(cut=True), controls=True, readers={"m7copy": SheetMap(cut=True, half=2.0)})
        self.assertFalse(res["controls"]["identity"]["pass"])
        self.assertIn("identity", res["controls"]["failed"])
        self.assertFalse(res["controls"]["valid"])
        # on real data the second reader is LocalZarr on m7's own cached files, not ChunkReader
        with tempfile.TemporaryDirectory() as t:
            m7dir = Path(t) / sb.PRED_M7.rsplit("/", 1)[-1] / "0"
            write_zarr(m7dir, SheetMap(), [])
            rd = sb._reader("m7copy", t, None)
            self.assertIsInstance(rd, sb.LocalZarr)
            self.assertEqual(rd.root, m7dir)

    # ------------------------------------------------------------ guards

    def test_guards_fail_on_what_they_guard_and_hold_on_m7(self):
        chunks = self.chunks_of(self.good)
        same = sb.pred_compare(chunks, "m7", "m7", self.prule)
        self.assertTrue(all(same["guards_held"].values()), same["guards_held"])
        lat = sb.pred_compare(chunks, "m7:lattice", "m7", self.prule)
        self.assertFalse(lat["guards_held"]["g4"], lat["g4_continuity"])          # G4: sheets cut to pieces
        sh = sb.pred_compare(chunks, "m7:shift", "m7", self.prule)
        self.assertFalse(sh["guards_held"]["g1"], sh["g1_seated"])                # G1: off the sheets
        dil = sb.pred_compare(chunks, "m7:dilate", "m7", self.prule)
        self.assertFalse(dil["guards_held"]["thickness"], dil["thickness_ratio"])  # thicker bands
        self.assertFalse(dil["guards_held"]["volume"], dil["volume_ratio"])
        # G2: a map that fills the space between sheets
        fat = self.score_map(SheetMap(half=1.5), pred="fat", against="m7", readers={"fat": SheetMap(half=5.0)})
        self.assertFalse(fat["comparison"]["guards_held"]["g2"], fat["comparison"]["g2_fill"])
        self.assertFalse(fat["comparison"]["beats"])

    def test_volume_guard_is_one_sided_so_a_candidate_can_beat_two_bars_of_different_volume(self):
        # two bars that merge the touching sheets, one thicker than the other; the candidate parts them and is
        # thinner than both: version 2 lets it pass against both, version 1's two-sided band stopped it
        readers = {"cand": SheetMap(cut=True), "thick": SheetMap(half=2.5, fill=True)}
        res = self.score_map(SheetMap(fill=True), pred="cand", against=["m7", "thick"], readers=readers)
        cmps = res["comparisons"]
        self.assertLess(cmps["m7"]["volume_ratio"]["ci"][1], 1.0)
        self.assertLess(cmps["thick"]["volume_ratio"]["ratio"], cmps["m7"]["volume_ratio"]["ratio"])
        for bar, c in cmps.items():
            self.assertTrue(c["beats"], (bar, c["guards_held"], c["cs"]))
        self.assertTrue(res["beats_all"])
        old = self.score_map(SheetMap(fill=True), pred="cand", against=["m7", "thick"], readers=readers,
                             prule=self.prule1)
        self.assertFalse(old["comparisons"]["thick"]["guards_held"]["volume"])
        self.assertFalse(old["beats_all"])
        # the one-sided guard still fails a candidate with more volume than the bar
        fat = sb.pred_compare(self.chunks_of(self.good), "m7:dilate", "m7", self.prule)
        self.assertGreater(fat["volume_ratio"]["ci"][1], self.prule["guards"]["ratio_max"])
        self.assertFalse(fat["guards_held"]["volume"])

    def test_g4_does_not_count_a_merge_and_holds_for_both_sheets(self):
        # merged sheets: version 1 counted the merged component as A's continuity, version 2 does not
        v1 = self.score_map(SheetMap(fill=True), prule=self.prule1)["summary"]["m7"]["g4_continuity"]["value"]
        v2 = self.merged["summary"]["m7"]["g4_continuity"]["value"]
        self.assertGreater(v1, 0.9)
        self.assertLess(v2, 0.1)
        # the outer sheet of the counted contact (turn 2) cut to pieces: version 1 looked at A only
        b1 = self.score_map(SheetMap(cut=True, broken=2), prule=self.prule1)["summary"]["m7"]
        b2 = self.score_map(SheetMap(cut=True, broken=2))["summary"]["m7"]
        self.assertGreater(b1["g4_continuity"]["value"], 0.5)
        self.assertLess(b2["g4_continuity"]["value"], 0.2)
        self.assertLess(b2["g4_b"]["value"], b2["g4_a"]["value"])
        # and on the parted map both sides hold
        g = self.good["summary"]["m7"]
        self.assertGreater(min(g["g4_a"]["value"], g["g4_b"]["value"]), 0.9)

    # ------------------------------------------------------------ controls

    def test_controls_valid_with_separated_sheets_and_no_headroom(self):
        k = self.good["controls"]
        self.assertTrue(k["valid"], k["failed"])
        self.assertFalse(k["void"])
        for name in ("dilate", "lattice", "ct_matched"):
            self.assertFalse(k[name]["beats"], name)
        self.assertFalse(k["shift"]["g1_held"])
        self.assertLessEqual(k["displaced"]["ratio"], 0.5)
        self.assertGreaterEqual(k["displaced"]["relative_drop"], 0.5)
        # nothing to cut where the sheets are already apart: the oracle gains nothing, so the statement is made
        self.assertLess(k["headroom"]["gain"], 0.02)
        self.assertFalse(k["headroom"]["enough"])
        self.assertIn("cannot be beaten", k["headroom"]["statement"])

    def test_oracle_finds_headroom_where_sheets_merge_and_the_run_is_void(self):
        self.assertGreater(self.plain["controls"]["headroom"]["gain"], self.good["controls"]["headroom"]["gain"])
        k = self.merged["controls"]
        self.assertGreater(k["headroom"]["gain"], 0.5)
        self.assertGreater(k["headroom"]["ci"][0], 0)
        self.assertTrue(k["headroom"]["enough"])
        self.assertNotIn("statement", k["headroom"])
        # merged sheets are clean nowhere, so the displaced control has nothing to validate: VOID
        self.assertEqual(k["displaced"]["base_cs"], 0.0)
        self.assertFalse(k["displaced"]["pass"])
        self.assertTrue(k["void"])
        self.assertFalse(k["valid"])
        self.assertIn("displaced", k["failed"])

    def test_shift_control_fails_when_the_map_is_not_moved(self):
        p = copy.deepcopy(self.prule)
        p["controls"]["shift_vox"] = 0.0
        res = self.score_map(SheetMap(), controls=True, prule=p)
        self.assertTrue(res["controls"]["shift"]["g1_held"])
        self.assertIn("shift", res["controls"]["failed"])
        self.assertFalse(res["controls"]["valid"])

    def test_displaced_control_is_void_without_displacement_or_with_a_tighter_ratio(self):
        p = copy.deepcopy(self.prule)
        p["controls"]["displace_pitch"] = 0.0
        res = self.score_map(SheetMap(), controls=True, prule=p)
        self.assertEqual(res["controls"]["displaced"]["drop"], 0.0)
        self.assertEqual(res["controls"]["displaced"]["ratio"], 1.0)
        self.assertTrue(res["controls"]["void"])
        # the relative criterion itself: displaced lines keeping 30 of 50 clean lines (0.6) fail it, 20 (0.4) pass,
        # and a map clean nowhere cannot pass it
        def disp(base, moved, prule=self.prule):
            return sb._displaced([{"displaced": {"pairs": 100, "base_clean": base, "displaced_clean": moved}}], prule)

        self.assertFalse(disp(50, 30)["pass"])
        self.assertTrue(disp(50, 20)["pass"])
        self.assertEqual(disp(50, 20)["relative_drop"], 0.6)
        self.assertFalse(disp(0, 0)["pass"])
        # version 1 asked for an absolute drop of 0.30: 50 to 20 of 100 passed, 50 to 25 did not
        self.assertTrue(disp(50, 20, self.prule1)["pass"])
        self.assertFalse(disp(50, 25, self.prule1)["pass"])

    def test_a_control_that_beats_m7_makes_the_run_invalid(self):
        # the merged map with the oracle standing in for the dilated map: it beats m7 with every guard held, so the
        # run is invalid
        real = sb._arm_map

        def dilate_is_oracle(spec, blocks, ctx, prule):
            return real("m7:oracle" if spec == "m7:dilate" else spec, blocks, ctx, prule)

        with mock.patch.object(sb, "_arm_map", dilate_is_oracle):
            res = self.score_map(SheetMap(fill=True), controls=True)
        self.assertTrue(res["controls"]["dilate"]["beats"], res["controls"]["dilate"]["comparison"]["guards_held"])
        self.assertIn("dilate", res["controls"]["failed"])
        self.assertFalse(res["controls"]["valid"])

    def test_beat_needs_the_gain_and_every_guard(self):
        chunks = self.chunks_of(self.merged)
        o = sb.pred_compare(chunks, "m7:oracle", "m7", self.prule)
        self.assertTrue(o["cs_gain_met"])
        self.assertEqual(o["beats"], all(o["guards_held"].values()))
        strict = copy.deepcopy(self.prule)
        strict["beat"]["cs_gain"] = 2.0
        self.assertFalse(sb.pred_compare(chunks, "m7:oracle", "m7", strict)["beats"])
        tight = copy.deepcopy(self.prule)
        tight["guards"]["ratio_max"] = 0.5
        self.assertFalse(sb.pred_compare(chunks, "m7:oracle", "m7", tight)["beats"])

    # ------------------------------------------------------------ the reference oracle

    def test_oracle_patches_come_only_from_lines_of_the_split(self):
        # a dev line inside the chunk and a line to a report winding just outside it: version 2 cuts only along
        # the dev line, version 1 took both
        lines = {"mid": np.array([[50.0, 50.0, 50.0], [100.0, 50.0, 50.0]]),
                 "n": np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])}
        in_split = np.array([True, False])
        v2 = sb._oracle_patches(lines, in_split, np.zeros(3), 96, self.prule)
        v1 = sb._oracle_patches(lines, in_split, np.zeros(3), 96, self.prule1)
        self.assertEqual(len(v2), 1)
        np.testing.assert_array_equal(v2[0][0], lines["mid"][0])
        self.assertEqual(len(v1), 2)

    def test_oracle_is_refused_on_the_report_split(self):
        for pred, against in (("m7:oracle", None), ("m7", "m7:oracle"), ("cand", ["m7", "m7:oracle"])):
            with self.assertRaisesRegex(sb.BenchError, "development"):
                sb.predscore(pred, against, split="report", refs_dir=self.refs_dir, rule=self.rule,
                             prule=self.prule, frozen="x")
        self.assertNotIn("m7:oracle", sb._control_arms(self.prule, "report"))
        self.assertIn("m7:oracle", sb._control_arms(self.prule, "dev"))
        # controls without the oracle say so instead of reporting a headroom
        chunks = [dict(c, arms={k: v for k, v in c["arms"].items() if k != "m7:oracle"})
                  for c in self.chunks_of(self.good)]
        k = sb.pred_controls(chunks, self.prule)
        self.assertFalse(k["headroom"]["run"])
        self.assertTrue(k["valid"], k["failed"])

    # ------------------------------------------------------------ matched-budget erosion null

    def test_erosion_null_removes_the_challengers_budget_from_both_faces(self):
        m = np.zeros((40, 40, 40), bool)
        m[10:30, 10:30, 15:24] = True                      # a slab 9 voxels thick
        union = np.zeros_like(m)
        union[5:35, 5:35, 5:35] = True
        chal = m.copy()
        chal[10:30, 10:30, 19] = False                      # a cut through the middle: 400 voxels
        out, budget = sb._erode_matched(m, chal, union, self.prule)
        self.assertEqual(budget, 400)
        self.assertEqual(int((m & ~out).sum()), 400)
        self.assertFalse((out & ~m).any())
        # peeled from the faces: every removed voxel is at least as near an off voxel as every kept one
        from scipy import ndimage
        d = ndimage.distance_transform_edt(m)
        self.assertLessEqual(d[m & ~out].max(), d[out & union].min())
        same, zero = sb._erode_matched(m, m, union, self.prule)
        self.assertEqual(zero, 0)
        np.testing.assert_array_equal(same, m)

    def test_a_cut_beats_its_erosion_null_and_a_plain_erosion_does_not(self):
        merged = SheetMap(fill=True)
        cut = self.score_map(merged, pred="cand", against=["m7", "m7:erode"], readers={"cand": SheetMap(cut=True)})
        self.assertTrue(cut["comparisons"]["m7:erode"]["beats"], cut["comparisons"]["m7:erode"]["guards_held"])
        self.assertTrue(any(c.get("erode_budget", {}).get("m7:erode") for c in cut["per_chunk"]))
        thin = self.score_map(merged, pred="cand", against=["m7", "m7:erode"], readers={"cand": Eroded(merged)})
        c = thin["comparisons"]["m7:erode"]
        self.assertFalse(c["beats"], c["cs"])
        self.assertLess(abs(c["cs"]["diff"]), 0.02)
        with self.assertRaisesRegex(sb.BenchError, "erosion null"):
            self.score_map(merged, pred="m7:erode")

    # ------------------------------------------------------------ masks

    def test_lines_outside_the_ct_mask_are_not_scored(self):
        cut = self.score_map(SheetMap(), ct=SyntheticCT(zero_from=1120))
        self.assertLess(cut["lines"], self.good["lines"])
        self.assertGreater(cut["lines"], 0)
        empty = self.score_map(SheetMap(), ct=SyntheticCT(zero_from=0))
        self.assertEqual(empty["lines"], 0)

    def test_seating_regions_and_volumes_count_only_inside_the_ct_mask(self):
        ct = SyntheticCT(zero_from=1105)          # line cubes around the row at z = 1100 reach into the mask
        on = self.score_map(SheetMap(), ct=ct)
        off_rule = copy.deepcopy(self.prule)
        off_rule["mask"] = {"ct_regions": False, "ct_volume": False}
        off = self.score_map(SheetMap(), ct=ct, prule=off_rule)
        self.assertEqual(on["lines"], off["lines"])
        self.assertLessEqual(on["regions"], off["regions"])
        rv = [sum(c["region_vertices"] for c in self.chunks_of(r)) for r in (on, off)]
        self.assertLess(rv[0], rv[1])
        vol_on = sum(c["arms"]["m7"]["vol"] for c in self.chunks_of(on))
        vol_off = sum(c["arms"]["m7"]["vol"] for c in self.chunks_of(off))
        self.assertLess(vol_on, vol_off)
        # with nothing masked inside the scroll the two agree
        a = self.score_map(SheetMap())
        b = self.score_map(SheetMap(), prule=off_rule)
        self.assertEqual(a["regions"], b["regions"])

    def test_ct_level_matches_m7s_volume(self):
        rng = np.random.default_rng(0)
        ct = rng.integers(0, 256, size=(40, 40, 40)).astype(np.uint8)
        m7 = np.zeros(ct.shape, bool)
        m7[5:35, 5:35, 18:22] = True
        CL = types.SimpleNamespace(W=21, lo=np.array([[5, 5, 5], [10, 12, 8]]))
        tau = sb._ct_tau(ct, m7, CL)
        union = np.zeros(ct.shape, bool)
        for lo in CL.lo:
            union[lo[0]:lo[0] + 21, lo[1]:lo[1] + 21, lo[2]:lo[2] + 21] = True
        target = int(m7[union].sum())
        err = {v: abs(int((ct[union] >= v).sum()) - target) for v in range(1, 256)}
        self.assertEqual(err[tau], min(err.values()))
        self.assertLess(err[tau] / target, 0.05)

    # ------------------------------------------------------------ missing and absent chunks

    def test_a_missing_chunk_of_a_published_source_is_excluded_for_every_arm(self):
        first = next(c for c in self.good["per_chunk"] if c.get("lines"))
        key = tuple(int(v) for v in first["chunk"].split("_"))
        res = self.score_map(SheetMap(), pred="m7", against="recto090",
                             readers={"recto090": SheetMap(half=2.5, missing=[key])})
        self.assertIn(first["chunk"], res["excluded_chunks"])
        self.assertEqual(res["excluded_chunks"][first["chunk"]], {"recto090": 1})
        self.assertEqual(res["lines"], self.good["lines"] - first["lines"])
        self.assertEqual(res["measured_chunks"], self.good["measured_chunks"] - 1)
        # the same lines for m7 alone: the chunk is gone for it too
        self.assertEqual(res["summary"]["m7"]["cs"]["n"], res["lines"])

    def test_a_hole_in_a_candidates_zarr_reads_as_empty_and_is_never_excluded(self):
        keys = [tuple(int(v) for v in c["chunk"].split("_")) for c in self.chunks_of(self.good)]
        with tempfile.TemporaryDirectory() as t:
            path = write_zarr(Path(t) / "cand.zarr" / "0", SheetMap(cut=True), keys)
            full = self.score_map(SheetMap(), pred=str(path.parent), against="m7")
            busiest = max(self.chunks_of(self.good), key=lambda c: c["lines"])
            (path / busiest["chunk"].replace("_", "/")).unlink()
            holed = self.score_map(SheetMap(), pred=str(path.parent), against="m7")
        self.assertEqual(holed["excluded_chunks"], {})
        self.assertEqual(holed["measured_chunks"], full["measured_chunks"])
        self.assertEqual(holed["lines"], full["lines"])
        self.assertEqual(holed["readers"][str(path.parent)]["absent"], 1)
        cs_full = full["summary"][str(path.parent)]["cs"]["value"]
        cs_holed = holed["summary"][str(path.parent)]["cs"]["value"]
        self.assertGreater(busiest["arms"]["m7"]["clean"], 0)
        self.assertAlmostEqual(cs_full - cs_holed, busiest["arms"]["m7"]["clean"] / full["lines"], places=3)

    def test_block_reads_across_chunk_grids_and_counts_missing(self):
        ct = SyntheticCT(chunk=64)
        blk, miss = sb._read_block(ct, (96, 96, 96), 96)
        z, y, x = grid((1, 1, 1), 96)
        rk, r = turn_radii(z, y, x)
        want = np.where(np.abs(r[None] - rk).min(0) <= 1.5, 200, 60)
        want = np.where(r > R0 + 8 * PITCH, 0, want)
        np.testing.assert_array_equal(blk, want)
        self.assertEqual(miss, 0)
        blk, miss = sb._read_block(SheetMap(chunk=64, missing=[(1, 1, 1)]), (96, 96, 96), 96)
        self.assertEqual(miss, 1)

    def test_local_zarr_reader_checks_the_frame_and_dtype(self):
        a = np.arange(64, dtype=np.uint8).reshape(4, 4, 4)

        class One:
            chunks = (4, 4, 4)

            def read(self, idx):
                return a

        with tempfile.TemporaryDirectory() as t:
            small = write_zarr(Path(t) / "small.zarr" / "0", One(), [(0, 0, 1)], chunk=4, shape=[8, 8, 8],
                               fill_value=7)
            with self.assertRaisesRegex(sb.BenchError, "not m7's"):
                sb.LocalZarr(small.parent)
            with self.assertRaisesRegex(sb.BenchError, "offset and threshold"):
                sb.LocalZarr(small.parent, offset=(0, 0, 0))
            rd = sb.LocalZarr(small.parent, offset=(100, 0, 0), threshold=5)
            self.assertEqual(rd.declared, {"offset": [100, 0, 0], "threshold": 5})
            np.testing.assert_array_equal(rd.read((0, 0, 1)), a)
            np.testing.assert_array_equal(rd.read((1, 0, 0)), np.full((4, 4, 4), 7, np.uint8))  # fill value
            blk, miss = sb._read_block(rd, (100, 2, 2), 4)                  # the offset moves the array
            np.testing.assert_array_equal(blk[:, :2, 2:], a[:, 2:, :2])
            np.testing.assert_array_equal(blk[:, :2, :2], 7)
            self.assertEqual(miss, 0)
            blk, _ = sb._read_block(rd, (0, 0, 4), 4)                        # before its voxel 0: zeros
            self.assertFalse(blk.any())
            # a float map in m7's frame is refused without an explicit threshold
            flt = write_zarr(Path(t) / "float.zarr" / "0", One(), [], chunk=4, dtype="<f4")
            with self.assertRaisesRegex(sb.BenchError, "dtype"):
                sb.LocalZarr(flt.parent)
            sb.LocalZarr(flt.parent, offset=(0, 0, 0), threshold=0.5)
            with self.assertRaises(sb.BenchError):
                sb.LocalZarr(Path(t))
        # the explicit offset and threshold enter the run rule
        man, _ = self.loaded
        plain = sb.pred_run_rule("dev", [1], man, self.rule, self.prule)
        decl = sb.pred_run_rule("dev", [1], man, self.rule, self.prule, local={"c.zarr": {"threshold": 5}})
        self.assertEqual(decl["local_maps"], {"c.zarr": {"threshold": 5}})
        self.assertNotIn("local_maps", plain)
        self.assertNotEqual(sb.digest(plain), sb.digest(decl))

    def test_a_local_map_that_never_reaches_the_threshold_is_refused(self):
        keys = [tuple(int(v) for v in c["chunk"].split("_")) for c in self.chunks_of(self.good)]
        with tempfile.TemporaryDirectory() as t:
            path = write_zarr(Path(t) / "ones.zarr" / "0", SheetMap(cut=True, value=1), keys)
            with self.assertRaisesRegex(sb.BenchError, "threshold"):
                self.score_map(SheetMap(), pred=str(path.parent), against="m7")
            res = self.score_map(SheetMap(), pred=str(path.parent), against="m7",
                                 local={str(path.parent): {"offset": [0, 0, 0], "threshold": 1}})
        self.assertEqual(res["run_rule"]["local_maps"], {str(path.parent): {"offset": [0, 0, 0], "threshold": 1}})
        self.assertEqual(res["summary"][str(path.parent)]["cs"], self.good["summary"]["m7"]["cs"])

    # ------------------------------------------------------------ a box released on its own

    def test_box_only_scoring(self):
        k, box = self.busiest()
        boxmap = InBox(SheetMap(cut=True), box)
        inbox = self.score_map(SheetMap(cut=True), pred="boxed", against="m7", readers={"boxed": boxmap}, box=box)
        self.assertEqual(inbox["run_rule"]["box"], box)
        self.assertEqual(inbox["run_rule"]["chunks"], ["_".join(map(str, k))])
        self.assertGreater(inbox["lines"], 10)
        self.assertEqual(inbox["comparison"]["cs"]["diff"], 0.0)
        # scored on the whole sample instead, the box map loses everything outside its box
        whole = self.score_map(SheetMap(cut=True), pred="boxed", against="m7", readers={"boxed": boxmap})
        self.assertLess(whole["comparison"]["cs"]["diff"], -0.5)
        # a box with no development line in it is refused
        with self.assertRaisesRegex(sb.BenchError, "under the box"):
            self.score_map(SheetMap(), box=[0, 96, 0, 96, 0, 96])

    def test_frame_check_passes_in_frame_and_fails_when_moved(self):
        _, box = self.busiest()
        m7 = SheetMap()
        ok = sb.pred_framecheck("cand", box, self.refs_dir, rule=self.rule, prule=self.prule,
                                readers={"m7": m7, "cand": SheetMap()})
        self.assertTrue(ok["pass"], ok)
        self.assertEqual(ok["best_shift"], [0, 0, 0])
        self.assertEqual(ok["dice_at_zero"], 1.0)
        moved = sb.pred_framecheck("cand", box, self.refs_dir, rule=self.rule, prule=self.prule,
                                   readers={"m7": m7, "cand": Offset(SheetMap(), (0, 0, 3))})
        self.assertFalse(moved["pass"])
        self.assertEqual(moved["best_shift"], [0, 0, -3])
        # a box whose every chunk holds report geometry is not checked at all
        w306 = next(r for r in self.loaded[1] if r.name == "w306")
        p = w306.xyz[w306.valid][len(w306.xyz[w306.valid]) // 2][::-1]
        k = np.floor_divide(p, 96).astype(int)
        rbox = [v for i in k for v in (int(i) * 96, int(i) * 96 + 96)]
        rep = sb.pred_framecheck("cand", rbox, self.refs_dir, rule=self.rule, prule=self.prule,
                                 readers={"m7": m7, "cand": SheetMap()})
        self.assertFalse(rep["pass"])
        self.assertEqual(rep["chunks_used"], [])

    def test_cli_prints_the_run_rule_digest(self):
        import argparse
        import io
        from contextlib import redirect_stdout
        p = argparse.ArgumentParser()
        sb.build_parser(p)
        args = p.parse_args(["predscore", "m7", "--rule-only", "--json", "--refs", str(self.refs_dir)])
        buf = io.StringIO()
        with mock.patch.object(sb, "RULE", self.rule), mock.patch.object(sb, "PRED_RULE", self.prule), \
                redirect_stdout(buf):
            self.assertEqual(sb.cmd_surfbench(args), 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["run_rule_digest"], sb.digest(out["run_rule"]))
        self.assertEqual(out["run_rule"]["pred_rule"], self.prule)
        args = p.parse_args(["predscore", "m7", "--rule-only", "--json", "--rule-version", "1", "--refs",
                             str(self.refs_dir)])
        buf = io.StringIO()
        with mock.patch.object(sb, "RULE", self.rule), redirect_stdout(buf):
            self.assertEqual(sb.cmd_surfbench(args), 0)
        self.assertEqual(json.loads(buf.getvalue())["run_rule"]["pred_rule"], sb.PRED_RULE_V1)


@unittest.skipIf(np is None, "numpy is needed")
class ChunkReaderTest(unittest.TestCase):
    def test_threads_asking_for_one_chunk_fetch_it_once(self):
        # predscore's neighbouring chunks share CT and recto-090 chunks; two threads downloading one chunk at once
        # shared its .part file, and a third read it while it was being written (an empty chunk on 9 Oct 2026)
        import collections
        import concurrent.futures
        import threading
        import time as _time
        meta = json.dumps({"chunks": [4, 4, 4], "dtype": "|u1", "compressor": None, "shape": [8, 8, 8],
                           "dimension_separator": "/", "order": "C", "fill_value": 0, "zarr_format": 2}).encode()
        body = np.arange(64, dtype=np.uint8).tobytes()
        calls, lock = collections.Counter(), threading.Lock()

        class Resp:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=60):
            url = getattr(req, "full_url", req)
            with lock:
                calls[url.split("pred.zarr/0/", 1)[-1]] += 1
            if url.endswith(".zarray"):
                return Resp(meta)
            _time.sleep(0.05)
            return Resp(body)

        with tempfile.TemporaryDirectory() as t:
            rd = sb.ChunkReader("X/pred.zarr", t, opener)
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                out = list(pool.map(lambda _: rd.read((0, 0, 1)), range(8)))
        self.assertEqual(calls["0/0/1"], 1)
        for a in out:
            np.testing.assert_array_equal(a, np.arange(64, dtype=np.uint8).reshape(4, 4, 4))
        self.assertEqual((rd.fetched, rd.cached), (1, 7))


# ---------------------------------------------------------------- gscore (stage 2: per-winding credit of a trace)

def fold_counter(xyz, valid, path=None):
    """A stand-in for VC3D's self-crossing census on the synthetic spiral, whose turns run in increasing angle along
    their rows: the row steps that go backward in angle, each a contact at the step's midpoint. A fold makes `back`
    of them per row; a surface that follows the spiral makes none."""
    th = np.arctan2(xyz[..., 1] - CY, xyz[..., 0] - CX)
    d = (th[:, 1:] - th[:, :-1] + math.pi) % (2 * math.pi) - math.pi
    hit = (d < 0) & valid[:, 1:] & valid[:, :-1]
    mid = 0.5 * (xyz[:, 1:] + xyz[:, :-1])[hit]
    return {"count": int(hit.sum()), "sites": [[round(float(v), 2) for v in p] for p in mid]}


def gscore_rule(version=None):
    from kit import gscore as gs
    g = copy.deepcopy(gs.GRULES[version or gs.GRULE["version"]])
    g["band_z"] = [1100.0, 1400.0]
    g["split"] = {"tune": ["w105", "w101", "w103", "w100", "w102"], "report": ["w107"], "excluded": ["w104"],
                  "note": "synthetic"}
    g["controls"]["nogrid_windings"] = ["w100"]
    g["controls"]["nogrid_size"] = [16, 16]
    g["controls"]["confetti_tiles"] = 6
    if "window" in g:
        g["window"]["side_vox"] = 300.0          # the synthetic band's height
        g["controls"]["whole_mesh_windings"] = ["w100"]
    for k in g["gates"]:
        g["gates"][k]["threshold"] = None        # the synthetic controls set their own
    return g


def spiral_sweep(t0, t1, rows, ncol):
    """A surface that follows the spiral from angle t0 to t1 (radians over all turns), across seams."""
    th = np.linspace(t0, t1, ncol)
    T, Z = np.meshgrid(th, rows)
    r = spiral_r(T) + wave(Z)
    return np.stack([CX + r * np.cos(T), CY + r * np.sin(T), Z], -1), np.ones(T.shape, bool)


@unittest.skipIf(np is None, "numpy and scipy are needed")
class GscoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from kit import gscore as gs
        cls.gs = gs
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.rule = test_rule()
        cls.grule = gscore_rule()
        cls.refs_dir = cls.root / "refs"
        cls.man = sb.build_manifest(cls.refs_dir, stack(cls.root), rule=cls.rule)
        cls.man, cls.refs = sb.load_refs(cls.refs_dir, cls.rule, seat=False)
        cls.by = {r.name: r for r in cls.refs}
        cls.cache = cls.root / "cache"
        cls.ctl = {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def controls(self, name, grule=None, rule=None, counter=fold_counter):
        key = (name, id(grule), id(rule), id(counter))
        if grule is None and rule is None and counter is fold_counter and key in self.ctl:
            return self.ctl[key]
        out = self.gs.winding_controls(self.by[name], self.refs, self.man, rule or self.rule, grule or self.grule,
                                       counter, self.refs_dir, self.cache)
        if grule is None and rule is None and counter is fold_counter:
            self.ctl[key] = out
        return out

    def frozen(self, names=("w100", "w105")):
        """The rule with the gate thresholds the controls on `names` give."""
        recs = [self.controls(n) for n in names]
        gates = self.gs.choose_gates(recs, self.grule)
        g = copy.deepcopy(self.grule)
        for k, v in gates.items():
            self.assertIsNotNone(v["threshold"], gates)
            g["gates"][k]["threshold"] = v["threshold"]
        return g, gates

    def score(self, xyz, valid, targets, grule=None, **kw):
        return self.gs.score_grid(xyz, valid, [self.by[t] for t in targets], self.refs, self.man, self.refs_dir,
                                  counter=fold_counter, rule=self.rule, grule=grule or self.grule,
                                  cache_dir=self.cache, **kw)

    # ------------------------------------------------------------ the rule

    def test_rule_digest_and_named_draws(self):
        gs = self.gs
        self.assertEqual(gs.GRULE_DIGEST, gs.grule_digest(gs.GRULE))
        g = copy.deepcopy(gs.GRULE)
        g["gates"]["switch"]["step"] = 0.02
        self.assertNotEqual(gs.grule_digest(g), gs.GRULE_DIGEST)
        self.assertEqual(gs.GRULE["surfbench_rule_digest"], sb.RULE_DIGEST)
        self.assertEqual(gs.GRULE["band_z"], [4352.0, 4864.0])
        # version 1: the thresholds the real controls gave (docs/logs/2026-10-09-trace-gscore.md), frozen before any score
        self.assertEqual(gs.GRULE_V1["version"], 1)
        self.assertEqual(gs.GRULE_V1["gates"]["switch"]["threshold"], 0.08)
        self.assertEqual(gs.GRULE_V1["gates"]["selfcross"]["threshold"], 42.0)
        self.assertEqual(gs.GRULE_V1_DIGEST, gs.grule_digest(gs.GRULE_V1))
        self.assertEqual(gs.GRULE_V1_DIGEST, "7a57f6dba46c7ea8b47c128b4084b10ba7813f7459c201aa9e1c4e8bb06db156")
        # version 2: thresholds stay None until a controls run on the tune meshes freezes them
        self.assertEqual(gs.GRULE["version"], 2)
        self.assertIsNone(gs.GRULE["gates"]["switch"]["threshold"])
        self.assertIsNone(gs.GRULE["gates"]["selfcross"]["threshold"])
        self.assertEqual(gs.GRULE["window"]["side_vox"], 512.0)
        self.assertEqual(gs.GRULE["controls"]["whole_mesh_windings"], ["w024", "w035", "w036"])
        self.assertEqual(gs.GRULE_DIGEST, "6da62ec433b20fff22b13f4df9ea2a414901a2e708acbdf18fc00a710bcc7dd4")
        # the windings the rule names come from seeded draws over the tune windings, not from looking at them
        tune = gs.GRULE["split"]["tune"]
        self.assertEqual(sorted(np.random.default_rng(0).choice(tune, 5, replace=False).tolist()),
                         gs.GRULE["aa"]["windings"])
        self.assertEqual(sorted(np.random.default_rng(1).choice(tune, 3, replace=False).tolist()),
                         gs.GRULE["controls"]["nogrid_windings"])
        rep = gs.GRULE["split"]["report"]
        self.assertEqual(sorted(np.random.default_rng(2).choice(rep, 3, replace=False).tolist()),
                         gs.GRULE["controls"]["nogrid_report_windings"])
        self.assertEqual(rep, ["w043", "w044"] + [f"w{n:03d}" for n in range(47, 60)])
        self.assertFalse(set(rep) & set(tune))
        self.assertFalse({"w045", "w046"} & set(rep))

    def test_choose_gates(self):
        gs = self.gs
        rec = {"positives": {"band": {"switch": 0.0, "selfcross": -1.0}, "seam": {"switch": 0.01, "selfcross": 2.0}},
               "negatives": {"transverse": {"switch": 0.2}, "fold": {"selfcross": 60.0}}}
        out = gs.choose_gates([rec], gs.GRULE)
        self.assertAlmostEqual(out["switch"]["threshold"], 0.1)       # midpoint 0.105 floored to 0.01
        self.assertAlmostEqual(out["selfcross"]["threshold"], 31.0)   # midpoint 31.0
        close = {"positives": {"band": {"switch": 0.1, "selfcross": 0.0}},
                 "negatives": {"transverse": {"switch": 0.12}, "fold": {"selfcross": 6.0}}}
        out = gs.choose_gates([close], gs.GRULE)
        self.assertIsNone(out["switch"]["threshold"])
        self.assertIn("no threshold", out["switch"]["reason"])
        self.assertIsNone(out["selfcross"]["threshold"])
        self.assertIsNone(gs.choose_gates([{"positives": {}, "negatives": {}}], gs.GRULE)["switch"]["threshold"])

    # ------------------------------------------------------------ reach and credit

    def test_a_reference_is_credited_in_full(self):
        for name in ("w100", "w105"):
            A = self.by[name]
            res = self.score(A.xyz, A.valid, [name], best=True)
            self.assertGreater(res["windings"][name]["G"], 0.99, res["windings"][name])
            self.assertEqual(res["windings"][name]["wrong_cm2"], 0.0)

    def test_following_the_spiral_across_a_seam_is_not_penalised(self):
        rows = np.arange(1080.0, 1421.0, STEP)
        k = 4                                               # turn 4 (w100) into turn 5 (w102) across their seam
        xyz, valid = spiral_sweep(2 * math.pi * k + 0.3, 2 * math.pi * (k + 1) + 2.0, rows, 200)
        res = self.score(xyz, valid, ["w100", "w102"], seed=xyz[8, 20])
        a, b = res["windings"]["w100"], res["windings"]["w102"]
        self.assertGreater(a["G"], 0.8)
        self.assertGreater(b["G"], 0.2)                    # the part past the seam is reached and credited
        self.assertEqual(a["wrong_cm2"], 0.0)              # and not counted against the trace
        self.assertGreater(a["seam_cm2"], 0.1)
        self.assertGreater(res["reach"]["links"]["linked_pairs"], 0)

    def test_a_transverse_switch_is_penalised(self):
        rows = np.arange(1080.0, 1421.0, STEP)
        a, va = winding(4, math.radians(20), math.radians(160), rows=rows, ncol=40)
        b, _ = winding(5, math.radians(20), math.radians(160), rows=rows, ncol=40)
        hard = np.concatenate([a[:, :20], b[:, 20:]], 1)
        res = self.score(hard, va, ["w100", "w102"], seed_rc=(8, 5))
        A, B = res["windings"]["w100"], res["windings"]["w102"]
        self.assertGreater(A["G"], 0.1)
        self.assertEqual(B["G"], 0.0)                      # the switched part is not reached
        self.assertGreater(A["wrong_cm2"], 0.05)           # and it counts against the net area
        self.assertLess(A["net_cm2"], A["covered_cm2"] - 0.05)
        # seeded on the other side, the credit goes the other way
        res = self.score(hard, va, ["w100", "w102"], seed_rc=(8, 35))
        self.assertEqual(res["windings"]["w100"]["G"], 0.0)
        self.assertGreater(res["windings"]["w102"]["G"], 0.1)

    def test_seed_on_no_winding(self):
        rows = np.arange(1080.0, 1421.0, STEP)
        a, va = winding(4, math.radians(20), math.radians(160), rows=rows, ncol=40)
        A = self.by["w100"]
        off = a.copy()
        n = np.array([a[..., 0] - CX, a[..., 1] - CY, 0 * a[..., 0]]).transpose(1, 2, 0)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        off[:, :3] = a[:, :3] + 8.0 * n[:, :3]              # three columns 8 voxels off the winding
        res = self.score(off, va, ["w100"], seed=off[8, 0])
        self.assertFalse(res["seed"]["on"])
        self.assertEqual(res["seed"]["moved_steps"], 3)
        self.assertGreater(res["windings"]["w100"]["G"], 0.1)
        far = a + 8.0 * n                                   # all of it off: nothing within the seed radius
        res = self.score(far, va, ["w100"], seed=far[8, 20])
        self.assertEqual(res["windings"]["w100"]["G"], 0.0)
        self.assertIn("reason", res["seed"])
        _ = A

    # ------------------------------------------------------------ the controls

    def test_controls_pass_on_the_spiral(self):
        for name in ("w100", "w105"):
            rec = self.controls(name)
            for k in ("band", "half_step", "seam", "transverse", "confetti"):
                self.assertTrue(rec[k]["pass"], (name, k, rec[k]))
            self.assertGreater(rec["band"]["G"], 0.99)
            self.assertTrue(all(m["kept"] <= 0.2 for m in rec["half_step"]["moves"]), rec["half_step"])
            # the band criterion (G at least 0.95) can fail: the same surface half a step off does not meet it
            self.assertTrue(all(m["G"] < 0.95 for m in rec["half_step"]["moves"]), rec["half_step"])
            self.assertAlmostEqual(rec["seam"]["G_next"], rec["seam"]["G_next_alone"], places=2)
            self.assertLess(rec["transverse"]["G_next"], 0.1 * rec["transverse"]["G_next_alone"])
            for arm in rec["confetti"]["arms"]:
                self.assertAlmostEqual(arm["G"], arm["largest_tile"], delta=0.005)
            self.assertLess(rec["confetti"]["arms"][0]["G"], 0.5 * rec["band"]["G"])
            self.assertGreater(rec["confetti"]["arms"][1]["torn_edges"], 0)
            self.assertGreater(rec["fold"]["selfcross"], 0)          # the fold is seen by the counter
        # on w100 the fold costs no credit; on w105 it sits at 180 degrees, where w101 is pressed to 3 voxels, so
        # its far side lands on w101 and is cut off as a switch (a fold in a contact zone is not free)
        self.assertGreater(self.controls("w100")["fold"]["G"], 0.9)
        self.assertGreater(self.controls("w105")["fold"]["switch_excess"], 0.1)
        ng = self.controls("w100")["nogrid"]
        self.assertTrue(ng["pass"], ng)
        self.assertTrue(all(a["G"] <= 0.05 for a in ng["arms"]))
        self.assertGreater(ng["sham"]["G"], 0.05)

    def test_gates_from_the_controls(self):
        g, gates = self.frozen()
        for k in ("switch", "selfcross"):
            self.assertLess(gates[k]["lo"] + g["gates"][k]["margin"], gates[k]["hi"])
        A = self.by["w100"]
        rec = self.gs.winding_controls(A, self.refs, self.man, self.rule, g, fold_counter, self.refs_dir, self.cache)
        # with the thresholds frozen: the band surface and the seam join pass both gates and keep their credit, the
        # transverse join fails the switch gate and the fold the self-crossing gate, so both get no credit
        self.assertTrue(rec["band"]["gates_pass"])
        self.assertEqual(rec["band"]["credit"], rec["band"]["G"])
        self.assertTrue(rec["seam"]["gates_pass"])
        self.assertTrue(rec["seam"]["pass"])
        self.assertFalse(rec["transverse"]["gates_pass"])
        self.assertEqual(rec["transverse"]["credit"], 0.0)
        self.assertTrue(rec["transverse"]["pass"])
        self.assertFalse(rec["fold"]["gates_pass"])
        self.assertEqual(rec["fold"]["credit"], 0.0)
        recs = [self.controls(n) for n in ("w100", "w105")]
        checks = self.gs.gate_checks(recs, g)
        self.assertTrue(all(c["pass"] for c in checks.values()), checks)
        self.assertIsNone(self.gs.gate_checks(recs, self.grule)["switch"])     # nothing to check before freezing
        # a threshold above the transverse joins' excess lets them through: the check fails and names them
        loose = copy.deepcopy(g)
        loose["gates"]["switch"]["threshold"] = 10.0
        bad = self.gs.gate_checks(recs, loose)["switch"]
        self.assertFalse(bad["pass"])
        self.assertEqual(bad["unmeasured"], [])
        self.assertEqual(bad["positives_passed"], bad["positives"])
        self.assertEqual(bad["negatives_caught"], 0)
        # every miss is a transverse join: the band join, or the same join planted in the whole mesh
        self.assertTrue(bad["misses"])
        self.assertTrue(all(m[1] in ("transverse", "whole_transverse") for m in bad["misses"]), bad["misses"])
        self.assertTrue(any(m[1] == "transverse" for m in bad["misses"]), bad["misses"])

    def test_run_controls_is_valid_only_under_the_thresholds_it_gives(self):
        gs = self.gs
        names = ["w100", "w105"]
        with mock.patch.object(gs, "vc3d_counter", lambda threads=2: fold_counter), \
                mock.patch.object(sb, "load_refs", lambda d, r=None: (self.man, self.refs)):
            unfrozen = gs.run_controls(self.refs_dir, names, rule=self.rule, grule=self.grule, cache_dir=self.cache)
            g = copy.deepcopy(self.grule)
            for k, v in unfrozen["gates"].items():
                g["gates"][k]["threshold"] = v["threshold"]
            frozen = gs.run_controls(self.refs_dir, names, rule=self.rule, grule=g, cache_dir=self.cache)
            off = copy.deepcopy(g)
            off["gates"]["selfcross"]["threshold"] += off["gates"]["selfcross"]["step"]
            moved = gs.run_controls(self.refs_dir, names, rule=self.rule, grule=off, cache_dir=self.cache)
            with self.assertRaises(gs.GError):
                gs.run_controls(self.refs_dir, ["w107"], rule=self.rule, grule=g, cache_dir=self.cache)
        self.assertFalse(unfrozen["failed"], unfrozen["summary"])
        self.assertFalse(unfrozen["valid"])                       # thresholds not in the rule yet
        self.assertTrue(frozen["valid"], (frozen["failed"], frozen["gates"], frozen["gate_checks"]))
        self.assertFalse(moved["valid"])                          # a rule threshold the controls do not give
        self.assertFalse(moved["gates"]["selfcross"]["rule_matches"])

    def test_half_step_control_fails_when_the_credit_distance_is_too_wide(self):
        # labels and credit at 10 voxels: a surface half a winding step (8 voxels) off keeps its credit
        rule = copy.deepcopy(self.rule)
        rule["distance"]["primary_vox"] = 10.0
        g = copy.deepcopy(self.grule)
        g["credit_vox"] = 10.0
        rec = self.controls("w100", grule=g, rule=rule)
        self.assertFalse(rec["half_step"]["pass"], rec["half_step"])
        self.assertGreater(max(m["kept"] for m in rec["half_step"]["moves"]), 0.2)
        # and its sham: a 1 voxel move keeps its credit, which the half-step criterion rejects
        self.assertTrue(self.controls("w100")["half_step"]["sham_fails"])

    def test_join_controls_fail_when_seams_are_not_told_from_switches(self):
        gs = self.gs
        real = gs._switch_test

        def all_switches(*a, **k):
            sw, ct = real(*a, **k)
            return np.ones_like(sw), ct

        def no_switches(*a, **k):
            sw, ct = real(*a, **k)
            return np.zeros_like(sw), ct

        with mock.patch.object(gs, "_switch_test", all_switches):
            rec = self.controls("w100", grule=copy.deepcopy(self.grule))
        self.assertFalse(rec["seam"]["pass"], rec["seam"])
        self.assertLess(rec["seam"]["G_next"], 0.01)
        with mock.patch.object(gs, "_switch_test", no_switches):
            rec = self.controls("w100", grule=copy.deepcopy(self.grule))
        self.assertFalse(rec["transverse"]["pass"], rec["transverse"])
        self.assertGreater(rec["transverse"]["G_next"], 0.5 * rec["transverse"]["G_next_alone"])

    def test_confetti_control_fails_without_reach_or_tears(self):
        gs = self.gs
        real = gs.reach_graph

        def one_component(*a, **k):
            out = real(*a, **k)
            out["comp"] = np.where(out["comp"] >= 0, 0, -1)
            return out

        with mock.patch.object(gs, "reach_graph", one_component):
            rec = self.controls("w100", grule=copy.deepcopy(self.grule))
        self.assertFalse(rec["confetti"]["pass"])
        self.assertGreater(rec["confetti"]["arms"][0]["G"], rec["confetti"]["arms"][0]["largest_tile"] + 0.1)
        g = copy.deepcopy(self.grule)
        g["reach"]["tear_factor"] = 1e9                    # no tears: the reversed tiles join up
        rec = self.controls("w100", grule=g)
        self.assertFalse(rec["confetti"]["pass"])
        shuffled = rec["confetti"]["arms"][1]
        self.assertGreater(shuffled["G"], shuffled["largest_tile"] + 0.1)

    def test_nogrid_control_fails_on_a_surface_that_follows_the_winding(self):
        gs = self.gs
        A = self.by["w100"]
        xyz, valid, nrm, sl = gs.band_surface(A, self.grule["band_z"])
        rc = gs.band_seed_rc(A, sl, self.grule["band_z"])

        def sc(x, v, targets, seed_rc=None, best=False):
            return self.score(x, v, [t.name for t in targets], seed_rc=seed_rc, best=best)

        c0 = rc[1] - 8
        out = gs.nogrid_controls(A, xyz, valid, nrm, sl, rc, sc, self.grule,
                                 nogrid=(xyz[:, c0:c0 + 16], valid[:, c0:c0 + 16], xyz[rc]))
        # the "no-grid trace" given here is the piece of the winding around the seed: it follows w100
        self.assertFalse(out["pass"])
        self.assertGreater(out["arms"][0]["G"], 0.05)
        self.assertTrue(out["sham_fails"])

    def test_gates_have_no_threshold_when_their_detector_is_blind(self):
        real = sb._crossings

        def blind(*a, **k):
            out = real(*a, **k)
            for key in ("switch_edges", "switch_edges_contact", "bridged_switches", "bridged_switches_contact",
                        "switch_crossings", "rows_with_switch"):
                out[key] = 0
            if k.get("sites") is not None:
                k["sites"].clear()                 # and it places no crossing
            return out

        with mock.patch.object(sb, "_crossings", blind):
            rec = self.controls("w100", grule=copy.deepcopy(self.grule))
        gates = self.gs.choose_gates([rec], self.grule)
        self.assertIsNone(gates["switch"]["threshold"], gates)
        rec = self.controls("w100", grule=copy.deepcopy(self.grule), counter=lambda x, v, p=None: 0)
        gates = self.gs.choose_gates([rec], self.grule)
        self.assertIsNone(gates["selfcross"]["threshold"], gates)

    def test_the_self_crossing_gate_excuses_only_the_references_own_contacts(self):
        gs = self.gs
        g, _ = self.frozen()
        A = self.by["w100"]
        xyz, valid, nrm, sl = gs.band_surface(A, g["band_z"])
        # the reference crosses itself at 12 sites of its own, on its band vertices in columns 4 to 6
        own = [[float(v) for v in xyz[2 + k % 6, 4 + k % 3]] for k in range(12)]
        rr = {"w100": {"switch_line_cm_per_cm2": 0.0, "selfcross": 12, "transverse_per_cm2": 1.0, "sites": own}}
        elsewhere = [[float(v) for v in xyz[2 + k % 6, 30 + k % 3]] for k in range(12)]

        def counter_of(n, sites):
            return lambda x, v, path=None: {"count": n, "sites": sites}

        def gate_of(x, v, n, sites):
            res = gs.score_grid(x, v, [A], self.refs, self.man, self.refs_dir, best=True, counter=counter_of(n, sites),
                                rule=self.rule, grule=g, cache_dir=self.cache, ref_rates=rr)
            return res["windings"]["w100"]["gates"]["selfcross"], res["rates"]["references_own_contacts"]

        # the band surface crossing itself where the reference does: none of it counts against it
        gate, mine = gate_of(xyz, valid, 12, own)
        self.assertEqual(mine, 12)
        self.assertAlmostEqual(gate["excess"], 0.0, places=3)
        self.assertTrue(gate["pass"])
        # the same number of crossings somewhere else (a fold): all of it counts
        gate, mine = gate_of(xyz, valid, 40, elsewhere + elsewhere + elsewhere + elsewhere[:4])
        self.assertEqual(mine, 0)
        self.assertAlmostEqual(gate["excess"], gate["rate"], places=3)
        self.assertGreater(gate["excess"], g["gates"]["selfcross"]["threshold"])
        self.assertFalse(gate["pass"])
        # 40 crossings piled on the reference's 12 sites: explained() still excuses 12. Version 2's gate rate is
        # the window max of the contacts that are not the references' (explain_sites, one to one), and the
        # reference rate passed to that gate is 0, so the excess equals the gate rate.
        res = gs.score_grid(xyz, valid, [A], self.refs, self.man, self.refs_dir, best=True,
                            counter=counter_of(40, (own * 4)[:40]), rule=self.rule, grule=g,
                            cache_dir=self.cache, ref_rates=rr)
        gate = res["windings"]["w100"]["gates"]["selfcross"]
        win = res["windows"]["selfcross"]
        mine = res["rates"]["references_own_contacts"]
        self.assertEqual(mine, 12)
        self.assertEqual(win["references_own"], 12)
        self.assertEqual(win["not_references"], 28)
        self.assertEqual(gate["reference_rate"], 0.0)
        self.assertAlmostEqual(gate["excess"], gate["rate"], places=4)
        # The synthetic frozen threshold is choose_gates on the planted folds' window rates. Those windows
        # are denser than these 28 contacts, so the excess is under that threshold and the gate passes.
        # (The unexcused case above is the one that threshold rejects.) The excess is still above version 1's
        # frozen threshold of 42.0.
        self.assertLess(gate["excess"], g["gates"]["selfcross"]["threshold"])
        self.assertTrue(gate["pass"])
        self.assertGreater(gate["excess"], gs.GRULE_V1["gates"]["selfcross"]["threshold"])
        # whole_surface_excess["selfcross"] is version 1's rate: transverse_per_cm2 minus own/area, with
        # own/area rounded to 3 decimals before the subtraction (rounded to 4). transverse_per_cm2 * 28/40
        # matches that to 2 decimal places; the leftover is that separate rounding of own/area.
        v1 = res["windings"]["w100"]["whole_surface_excess"]["selfcross"]
        rate = res["rates"]["transverse_per_cm2"]
        area = res["area_cm2"]
        self.assertEqual(v1, round(rate - round(mine / area, 3), 4))
        self.assertAlmostEqual(v1, rate * 28 / 40, places=2)
        # a counter that gives no sites excuses nothing
        res = gs.score_grid(xyz, valid, [A], self.refs, self.man, self.refs_dir, best=True,
                            counter=lambda x, v, path=None: 12, rule=self.rule, grule=g, cache_dir=self.cache,
                            ref_rates=rr)
        self.assertEqual(res["rates"]["references_own_contacts"], 0)
        self.assertEqual(gs.explained(own, [[p[0] + 4.5, p[1], p[2]] for p in own], 4.0), 0)
        self.assertEqual(gs.explained(own, [[p[0] + 3.5, p[1], p[2]] for p in own], 4.0), 12)
        _ = nrm, sl

    # ------------------------------------------------------------ scoring a tifxyz

    def test_score_reads_the_seed_and_refuses_report_windings(self):
        gs = self.gs
        g, _ = self.frozen()
        rows = np.arange(1080.0, 1421.0, STEP)
        xyz, valid = winding(4, math.radians(20), math.radians(160), rows=rows, ncol=40)
        d = self.root / "trace"
        sb.write_tifxyz(d, xyz, valid, {"format": "tifxyz", "type": "seg", "scale": [0.05, 0.05], "uuid": "t",
                                        "seed": [float(v) for v in xyz[8, 20]]})
        res = gs.score(d, None, self.refs_dir, counter=fold_counter, rule=self.rule, grule=g, cache_dir=self.cache)
        self.assertEqual(list(res["windings"]), ["w100"])                 # the winding its seed lies on
        self.assertTrue(res["valid"], res["invalid_reasons"])
        self.assertTrue(res["windings"]["w100"]["gates"]["pass"])
        self.assertGreater(res["windings"]["w100"]["credit"], 0.1)
        self.assertEqual(res["seed"]["vertex_rc"], [8, 20])
        # unfrozen thresholds or no self-crossing counter: no valid score
        res = gs.score(d, None, self.refs_dir, counter=fold_counter, rule=self.rule, grule=self.grule,
                       cache_dir=self.cache)
        self.assertFalse(res["valid"])
        self.assertIsNone(res["windings"]["w100"]["credit"])
        res = gs.score(d, None, self.refs_dir, counter=None, rule=self.rule, grule=g, cache_dir=self.cache)
        self.assertFalse(res["valid"])
        # a report winding takes its seed only from meta.json, under the current rule version, with the committed
        # run rule. --best and --seed are refused even when --frozen matches.
        w7, v7 = winding(6, math.radians(20), math.radians(120), rows=rows, ncol=30)
        rep = self.root / "rep"
        sb.write_tifxyz(rep, w7, v7)
        with self.assertRaisesRegex(sb.BenchError, "report"):
            gs.score(rep, ["w107"], self.refs_dir, best=True, counter=fold_counter, rule=self.rule,
                     grule=g, cache_dir=self.cache)
        rr = sb.digest(gs.run_rule(self.man, g))
        with self.assertRaisesRegex(sb.BenchError, r"no --best"):
            gs.score(rep, ["w107"], self.refs_dir, best=True, counter=fold_counter, rule=self.rule,
                     grule=g, cache_dir=self.cache, frozen=rr)
        with self.assertRaisesRegex(sb.BenchError, r"no --seed"):
            gs.score(rep, ["w107"], self.refs_dir, seed=[float(v) for v in w7[8, 20]], counter=fold_counter,
                     rule=self.rule, grule=g, cache_dir=self.cache, frozen=rr)
        # no seed in meta.json, correct frozen digest, no best: nothing is reached, so G is 0
        res = gs.score(rep, ["w107"], self.refs_dir, counter=fold_counter, rule=self.rule, grule=g,
                       cache_dir=self.cache, frozen=rr)
        self.assertEqual(res["windings"]["w107"]["G"], 0.0)
        sb.write_tifxyz(rep, w7, v7, {"format": "tifxyz", "type": "seg", "scale": [0.05, 0.05], "uuid": "t",
                                      "seed": [float(v) for v in w7[8, 20]]})
        res = gs.score(rep, ["w107"], self.refs_dir, counter=fold_counter, rule=self.rule, grule=g,
                       cache_dir=self.cache, frozen=rr)
        self.assertEqual(res["split"], {"w107": "report"})
        self.assertEqual(res["seed"]["source"], "meta.json")
        # the same report winding under version 1. Thresholds are copied from the frozen version 2 gates, and
        # frozen is that copy's own run-rule digest, so the refusal is the version: report windings are scored
        # only under the current one.
        g1 = gscore_rule(1)
        for k in g1["gates"]:
            g1["gates"][k]["threshold"] = g["gates"][k]["threshold"]
        with self.assertRaisesRegex(sb.BenchError, "current rule version"):
            gs.score(rep, ["w107"], self.refs_dir, counter=fold_counter, rule=self.rule, grule=g1,
                     cache_dir=self.cache, frozen=sb.digest(gs.run_rule(self.man, g1)))
        with self.assertRaisesRegex(sb.BenchError, "tune"):
            gs.run_controls(self.refs_dir, ["w107"], counter=fold_counter, rule=self.rule, grule=g)


if __name__ == "__main__":
    unittest.main()
