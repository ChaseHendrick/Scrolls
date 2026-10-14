"""Tests for kit.stackcheck on synthetic spiral stacks built here (no downloads).

A clean stack of six windings of an Archimedean spiral, each segment exactly one turn, passes every check; each
planted defect (a missing sector, an inversion, a skipped winding, a turn overlap, a missing stack end) is flagged
by its own check, so every check can fail."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

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

    def test_spacing_and_pitch_are_measured(self):
        for p in self.rep["order"]["pairs"]:
            self.assertEqual(p["inverted_rays"], 0)
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
        self.assertLess(r["next"]["distance_um_q5_25_50_75_95"][2], 1.0)
        self.assertGreater(r["next"]["next_vertices_at_same_height_and_angle"], 50)
        self.assertTrue(masks["w03"]["turn_overlap"].any())
        self.assertFalse(masks["w04"]["turn_overlap"].any())

    def test_missing_stack_end(self):
        segs = stack()
        segs[3][1] &= segs[3][0][..., 2] >= 150
        rep, _ = check(segs)
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
