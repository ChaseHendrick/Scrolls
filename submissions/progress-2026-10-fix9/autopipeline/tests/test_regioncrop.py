"""kit meshqa crop (kit/regioncrop.py): the region crop on synthetic sheets, its tifxyz output and its command."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    import scipy  # noqa: F401 - the crossing cut needs scipy.ndimage
    HAVE_NUMPY = True
except ImportError:     # pragma: no cover
    HAVE_NUMPY = False

from kit import regioncrop  # noqa: E402

SHEETS = (18, 32, 46)        # three windings along z, pitch 14
UNIT = 9.362
SMALL = {"regions": {"min_area_cm2": 0.001}}


def volumes():
    """(CT, prediction) as (z, y, x) arrays: bright sheets 3 voxels thick at SHEETS, dim elsewhere (never 0)."""
    z = np.arange(64)[:, None, None]
    on = np.zeros((64, 1, 1), bool)
    for s in SHEETS:
        on |= np.abs(z - s) <= 1
    ct = np.where(on, 200, 20).astype(np.uint8) * np.ones((1, 200, 200), np.uint8)
    pred = np.where(on, 255, 0).astype(np.uint8) * np.ones((1, 200, 200), np.uint8)
    return ct, pred


def grid(rows=41, cols=41, z=32.0, step=4.0):
    """A flat sheet at height z, x = 8 + step * col, y = 8 + step * row: +N points along z."""
    r, c = np.mgrid[0:rows, 0:cols]
    xyz = np.stack([8.0 + step * c, 8.0 + step * r, np.full(r.shape, z)], -1).astype(np.float64)
    return xyz, np.ones((rows, cols), bool)


def write(path, xyz, valid, meta=None, scale=0.25):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    sub = np.where(valid[..., None], xyz, -1.0)
    for i, a in enumerate("xyz"):
        regioncrop._write_grid(path / f"{a}.tif", sub[..., i], "f32")
    m = {"format": "tifxyz", "type": "seg", "uuid": "source-uuid", "scale": [scale, scale]}
    m.update(meta or {})
    (path / "meta.json").write_text(json.dumps(m))
    return path


def band(row):
    """Contacts whose quads cover every vertex of rows row and row + 1 on a 41-column grid."""
    return [[row, c, row, c + 1] for c in range(0, 39, 2)]


def report(contacts):
    """A vc_tifxyz_selfcross report holding these contacts on diagonal 0."""
    return {"census": [{"diagonal": 0, "transverse": len(contacts),
                        "transverse_contacts": [{"quad1": [a, b], "quad2": [c, d]} for a, b, c, d in contacts]},
                       {"diagonal": 1, "transverse": 0, "transverse_contacts": []}]}


class TestUnits(unittest.TestCase):
    def test_the_size_of_a_coordinate_unit(self):
        u = regioncrop.coordinate_unit_um
        self.assertEqual(u({}, 9.362), (9.362, "voxel size 9.362 um given"))
        # villa #2112: a segment traced on a volume downscaled 2x, coordinates not scaled back
        self.assertEqual(u({"vc_open_data_original_volume_downscale": 2}, 2.4)[0], 4.8)
        self.assertEqual(u({"original_volume_downscale": "4"}, 2.4)[0], 9.6)
        # VC3D scaled them back already: the original voxel
        self.assertEqual(u({"vc_open_data_original_volume_downscale": 2,
                            "vc_open_data_coordinates_scaled_to_original_volume": 2}, 2.4)[0], 2.4)
        # villa #2175 writes the current voxel size at the top level
        self.assertEqual(u({"voxel_size_um": 7.91}), (7.91, "meta.json voxel_size_um"))
        self.assertEqual(u({"fit_config": {"voxel_size_um": 3.0}})[0], 3.0)
        self.assertIsNone(u({})[0])
        with self.assertRaises(regioncrop.CropError):
            u({}, -1.0)

    def test_whole_trace_arms(self):
        w = regioncrop.whole_trace(175, 12.534, 65.0)
        self.assertEqual((w["zero_tolerance"], w["calibrated"]), (False, True))
        self.assertAlmostEqual(w["per_cm2"], 13.962, places=3)
        self.assertEqual(regioncrop.whole_trace(0, 1.0, None)["calibrated"], None)
        self.assertEqual(regioncrop.whole_trace(None, 1.0, 65.0)["zero_tolerance"], None)

    def test_params(self):
        p = regioncrop.merged(None, selfcross__dilate=3, regions__min_area_cm2=None)
        self.assertEqual((p["selfcross"]["dilate"], p["regions"]["min_area_cm2"]),
                         (3, regioncrop.PARAMS["regions"]["min_area_cm2"]))
        self.assertNotEqual(regioncrop.params_digest(p), regioncrop.params_digest())
        for bad in ({"selfcross": {"dilate": -1}}, {"off_sheet": {"min_cells": 0}}, {"seating": {"fail": ["x"]}},
                    {"regions": {"connectivity": 8}}):
            with self.assertRaises(regioncrop.CropError):
                regioncrop.merged(bad)


@unittest.skipUnless(HAVE_NUMPY, "needs numpy and scipy")
class TestCut(unittest.TestCase):
    def test_crossings_cut_a_band_and_small_pieces_are_dropped(self):
        xyz, valid = grid()
        P = regioncrop.merged(SMALL, selfcross__dilate=0)
        # contacts along row 20 split the sheet into two halves
        contacts = band(20)
        rec, arr = regioncrop.cut_regions(xyz, valid, contacts=contacts, unit_um=UNIT, params=P)
        self.assertEqual(len(rec["regions"]), 2)
        self.assertTrue(arr["selfcross"][20:22, :].all())
        self.assertEqual(rec["cut_vertices"]["selfcross"], 2 * 41)
        self.assertLess(rec["kept_share"], 1.0)
        self.assertEqual(rec["measured"], {"selfcross": True, "seating": False, "off_sheet": False})
        # a dilation of 2 grows the band by 2 rows each side
        rec2, arr2 = regioncrop.cut_regions(xyz, valid, contacts=contacts, unit_um=UNIT,
                                            params=regioncrop.merged(SMALL, selfcross__dilate=2))
        self.assertEqual(rec2["cut_vertices"]["selfcross"], 6 * 41)
        # a minimum area above the smaller piece keeps only the larger
        big = regioncrop.merged({"regions": {"min_area_cm2": 0.009}}, selfcross__dilate=0)
        cut = band(30)
        rec3, _ = regioncrop.cut_regions(xyz, valid, contacts=cut, unit_um=UNIT, params=big)
        self.assertEqual(len(rec3["regions"]), 1)
        self.assertEqual(rec3["dropped_small"]["pieces"], 1)
        # cm2 without a voxel size is refused
        with self.assertRaises(regioncrop.CropError):
            regioncrop.cut_regions(xyz, valid, contacts=contacts, unit_um=None, params=P)

    def test_seating_on_a_tiling(self):
        ct, _ = volumes()
        from kit import switchfix
        xyz, valid = grid()
        wins = regioncrop.seating_grid(xyz, valid, switchfix.ArraySampler(ct), UNIT, window_cells=10)
        self.assertEqual(len(wins), 16)
        self.assertTrue(all(w["verdict"] == "seated" for w in wins), [w.get("contrast") for w in wins])
        self.assertEqual((wins[0]["rows"], wins[0]["cols"]), ([0, 11], [0, 11]))
        # the sheet moved half a pitch: between windings everywhere
        moved = xyz.copy()
        moved[..., 2] += 7
        wins = regioncrop.seating_grid(moved, valid, switchfix.ArraySampler(ct), UNIT, window_cells=10)
        self.assertTrue(all(w["verdict"] == "not seated" for w in wins), [w.get("contrast") for w in wins])
        # a block with too few valid quads is unmeasured, never cut
        holes = valid.copy()
        holes[:11, :11] = False
        wins = regioncrop.seating_grid(xyz, holes, switchfix.ArraySampler(ct), UNIT, window_cells=10)
        self.assertEqual(wins[0]["verdict"], "unmeasured")

    def test_a_patch_moved_into_air_is_cut_by_seating_and_off_sheet(self):
        ct, pred = volumes()
        from kit import switchfix
        xyz, valid = grid()
        xyz[10:21, 10:21, 2] += 7.0
        wins = regioncrop.seating_grid(xyz, valid, switchfix.ArraySampler(ct), UNIT, window_cells=10)
        bad = [w for w in wins if w["verdict"] == "not seated"]
        self.assertEqual([(w["rows"], w["cols"]) for w in bad], [([10, 21], [10, 21])])
        of, ch, cv, info, off_all = regioncrop.offsheet(xyz, valid, switchfix.ArraySampler(pred), 25)
        self.assertTrue(of[10:21, 10:21].all())
        self.assertEqual(int(of.sum()), 121)
        self.assertEqual(info["cut_blobs"], 1)
        rec, arr = regioncrop.cut_regions(xyz, valid, windows=wins, offsheet_mask=of, cut_h=ch, cut_v=cv,
                                          unit_um=UNIT, params=regioncrop.merged(SMALL))
        kept = arr["labels"] >= 0
        self.assertFalse(kept[10:21, 10:21].any())
        self.assertTrue(kept[0, 0] and kept[40, 40])
        self.assertEqual(len(rec["regions"]), 1)
        # a blob under min_cells is left: isolated misses of the prediction are not cut
        of2, *_ = regioncrop.offsheet(xyz, valid, switchfix.ArraySampler(pred), 122)
        self.assertFalse(of2.any())

    def test_windows_from_a_check_surface_record(self):
        seat = {"level": 0, "scale_segmentation": 1.0, "verdict": "partly seated",
                "windows": [{"window_xywh": [0, 0, 40, 40], "verdict": "not seated", "contrast": 1.0},
                            {"window_xywh": [80, 80, 40, 40], "verdict": "seated", "contrast": 30.0}]}
        w = regioncrop.load_windows(seat, {"scale": [0.25, 0.25]})
        self.assertEqual((w[0]["rows"], w[0]["cols"], w[0]["verdict"]), ([0, 11], [0, 11], "not seated"))
        self.assertEqual(w[1]["rows"], [20, 31])
        self.assertEqual(regioncrop.load_windows([{"rows": [0, 5], "cols": [0, 5], "verdict": "seated"}])[0]["rows"],
                         [0, 5])
        with self.assertRaises(regioncrop.CropError):
            regioncrop.load_windows([{"rows": [0, 5], "verdict": "seated"}])

    def test_a_count_only_report_cannot_be_cut(self):
        with self.assertRaises(regioncrop.CropError):
            regioncrop.load_selfcross({"census": [{"diagonal": 0, "transverse": 3}, {"diagonal": 1, "transverse": 0}]})
        rep = regioncrop.load_selfcross(report([[1, 1, 5, 5]]))
        self.assertEqual((rep["transverse"], rep["contacts"]), (1, [[1, 1, 5, 5]]))


@unittest.skipUnless(HAVE_NUMPY, "needs numpy and scipy")
class TestWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, meta=None):
        xyz, valid = grid()
        src = write(self.d / "trace.tifxyz", xyz, valid, {
            "vc_open_data_representation": {"id": "catalog"}, "vc_open_data_original_volume_downscale": 1,
            "area_vx2": 1.0, "bbox": [[0, 0, 0], [1, 1, 1]], "seed": [1, 2, 3], **(meta or {})})
        (src / "catalog-origin.json").write_text("{}")
        rp = self.d / "sc.json"
        rp.write_text(json.dumps(report(band(20))))
        return src, rp, xyz

    def test_each_piece_is_a_vc3d_tifxyz(self):
        src, rp, xyz = self.source()
        out = self.d / "pieces"
        rec = regioncrop.crop(src, out, selfcross=rp, voxel_um=UNIT,
                              params=regioncrop.merged(SMALL, selfcross__dilate=0))
        self.assertEqual(len(rec["regions"]), 2)
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(names, ["trace-r00.tifxyz", "trace-r01.tifxyz"])
        total = 0.0
        for r in rec["regions"]:
            p = Path(r["path"])
            self.assertEqual(sorted(f.name for f in p.iterdir()), ["meta.json", "x.tif", "y.tif", "z.tif"])
            m = json.loads((p / "meta.json").read_text())
            self.assertEqual(m["name"], p.name)
            self.assertNotEqual(m["uuid"], "source-uuid")
            self.assertEqual(m["uuid"], r["uuid"])
            self.assertNotIn("vc_open_data_representation", m)          # villa #2178
            self.assertEqual(m["vc_open_data_original_volume_downscale"], 1)
            self.assertEqual(m["seed"], [1, 2, 3])
            self.assertEqual(m["scale"], [0.25, 0.25])
            self.assertEqual(m["voxel_size_um"], UNIT)
            self.assertAlmostEqual(m["area_cm2"], m["area_vx2"] * (UNIT * 1e-4) ** 2)
            self.assertEqual(m["kit_regioncrop"]["source_uuid"], "source-uuid")
            # read back as VC3D loads it: the same vertices, at the same positions, bbox recomputed
            x2, v2, _, _ = regioncrop.read(p)
            r0, r1 = r["rows"]
            c0, c1 = r["cols"]
            self.assertEqual(x2.shape[:2], (r1 - r0, c1 - c0))
            self.assertTrue(np.allclose(x2[v2], xyz[r0:r1, c0:c1][v2]))
            self.assertEqual(m["bbox"][0], [float(v) for v in x2[v2].min(0)])
            total += m["area_cm2"]
        self.assertAlmostEqual(total, rec["kept_area_cm2"], places=4)
        self.assertFalse(any(p.name.endswith(".partial") for p in out.iterdir()))
        # an existing piece is not replaced without overwrite
        with self.assertRaises(regioncrop.CropError):
            regioncrop.crop(src, out, selfcross=rp, voxel_um=UNIT, params=regioncrop.merged(SMALL, selfcross__dilate=0))
        regioncrop.crop(src, out, selfcross=rp, voxel_um=UNIT, overwrite=True,
                        params=regioncrop.merged(SMALL, selfcross__dilate=0))
        with self.assertRaises(regioncrop.CropError):
            regioncrop.crop(src, src / "inside", selfcross=rp, voxel_um=UNIT, params=regioncrop.merged(SMALL))


    def villa_load(self, path, erode_cells=1):
        """villa's spiral-fitting patch loader, step for step, without torch (ChaseHendrick/villa 4eecd08f:
        tifxyz.py load_tifxyz reads meta.json's scale and uuid and the three bands with PIL, a vertex is valid when
        any coordinate is not -1, Patch asserts a valid quad; spiral_helpers.py erode_patch_valid_region erodes the
        valid region and drops a patch with no valid quad left). Returns (zyxs, valid, uuid) or None when dropped."""
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("needs Pillow")
        from scipy import ndimage
        meta = json.loads((Path(path) / "meta.json").read_text())
        self.assertIsInstance(meta, dict)
        sc = meta.get("scale")
        self.assertTrue(isinstance(sc, list) and len(sc) == 2 and all(type(v) in (int, float) and 0 < v < np.inf
                                                                      for v in sc))
        z = np.array(Image.open(f"{path}/z.tif"))
        y = np.array(Image.open(f"{path}/y.tif"))
        x = np.array(Image.open(f"{path}/x.tif"))
        zyxs = np.stack([z, y, x], -1).astype(np.float32)
        valid = np.any(zyxs != -1, axis=-1)
        quads = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
        self.assertTrue(quads.any())                                   # Patch.__post_init__'s assert
        # Patch.erosion_cells: meta.json's spiral_patch_erode_cells overrides the config default
        cells = int(meta["spiral_patch_erode_cells"]) if meta.get("spiral_patch_erode_cells") is not None \
            else erode_cells
        if cells > 0:
            eroded = ndimage.binary_erosion(valid, iterations=cells, border_value=0)
            q2 = eroded[:-1, :-1] & eroded[1:, :-1] & eroded[:-1, 1:] & eroded[1:, 1:]
            if not q2.any():
                return None
        return zyxs, valid, meta.get("uuid")

    def test_spiral_patches_load_as_villas_spiral_fitting_reads_them(self):
        from kit import villafmt
        xyz, valid = grid()
        src = write(self.d / "trace.tifxyz", xyz, valid)
        rp = self.d / "sc.json"
        rp.write_text(json.dumps(report(band(20) + band(24))))          # leaves a 2-row strip, rows 22 and 23
        vp = self.d / "dataset" / "verified_patches"
        tiny = regioncrop.merged({"regions": {"min_area_cm2": 0.0001}}, selfcross__dilate=0)
        rec = regioncrop.crop(src, None, selfcross=rp, voxel_um=UNIT, spiral_patches=vp, params=tiny)
        self.assertEqual(len(rec["regions"]), 3)
        sp = rec["spiral_patches"]
        strip = [r["index"] for r in rec["regions"] if r["rows"] == [22, 24]]
        self.assertEqual(sp["dropped"], strip)                         # villa's 1-cell erosion leaves no quad
        self.assertEqual(len(sp["written"]), 2)
        entries = sorted(p.name for p in vp.iterdir())
        self.assertEqual(len(entries), 2)                              # nothing else in the folder villa lists
        for r in rec["regions"]:
            if r["index"] not in sp["written"]:
                self.assertNotIn("spiral_patch", r)
                self.assertFalse(r["spiral_check"]["loads"])
                continue
            p = Path(r["spiral_patch"])
            self.assertEqual(p.parent, vp)
            got = self.villa_load(p)
            self.assertIsNotNone(got)
            zyxs, v2, uid = got
            self.assertEqual(uid, p.name)                              # uuid-named, as villa's entries are
            self.assertEqual(uid, r["spiral_patch_uuid"])
            r0, r1 = r["rows"]
            c0, c1 = r["cols"]
            self.assertTrue(np.allclose(zyxs[v2][:, ::-1], xyz[r0:r1, c0:c1][v2]))
            self.assertTrue(villafmt.check_tifxyz(p)["ok"])            # and VC3D's loader rules
            self.assertTrue(r["spiral_check"]["loads"])
            self.assertEqual(r["spiral_check"]["largest_share"], 1.0)
        with self.assertRaises(regioncrop.CropError):                  # a file in place of the folder
            (self.d / "afile").write_text("x")
            regioncrop.crop(src, None, selfcross=rp, voxel_um=UNIT, spiral_patches=self.d / "afile",
                            params=regioncrop.merged(SMALL, selfcross__dilate=0))

    def test_a_rerun_never_doubles_the_spiral_patches(self):
        """villa loads every entry of verified_patches, so a second run into the same folder must not add a second
        copy of each piece: the names are deterministic, a rerun without --overwrite is refused, and --overwrite
        replaces every patch an earlier run cut from the same surface (also when the pieces changed)."""
        from kit import cli
        src, rp, _ = self.source()
        vp = self.d / "dataset" / "verified_patches"
        other = vp / "someone-elses-patch"                              # never touched
        other.mkdir(parents=True)
        (other / "meta.json").write_text(json.dumps({"uuid": "someone-elses-patch", "scale": [1, 1]}))

        def run(*extra):
            o, e = io.StringIO(), io.StringIO()
            with redirect_stdout(o), redirect_stderr(e):
                code = cli.main(["meshqa", "crop", str(src), "--selfcross", str(rp), "--voxel-um", str(UNIT),
                                 "--min-area-cm2", "0.001", "--spiral-patches", str(vp), *extra])
            return code, o.getvalue() + e.getvalue()

        def ours():
            return sorted(p.name for p in vp.iterdir() if p.name != other.name)

        self.assertEqual(run("--dilate", "0", "--overwrite")[0], 0)
        first = ours()
        self.assertEqual(len(first), 2)
        self.assertEqual(run("--dilate", "0", "--overwrite")[0], 0)
        self.assertEqual(ours(), first)                                 # the same two names, not four entries
        code, text = run("--dilate", "0")                               # without --overwrite: refused
        self.assertNotEqual(code, 0)
        self.assertIn("--overwrite", text)
        self.assertEqual(ours(), first)
        # other settings cut other pieces: the earlier run's entries are replaced, not kept beside them
        code, text = run("--dilate", "0", "--no-jumps", "--min-area-cm2", "0.2", "--overwrite")
        self.assertEqual(ours(), [])
        self.assertEqual(run("--dilate", "1", "--overwrite")[0], 0)
        again = ours()
        self.assertEqual(len(again), 2)
        self.assertTrue(set(again).isdisjoint(first))                  # new params, new names, old ones removed
        self.assertTrue((other / "meta.json").is_file())
        u = regioncrop.spiral_patch_uuid(src, {"uuid": "source-uuid"}, 0, "d")
        self.assertEqual(u, regioncrop.spiral_patch_uuid(self.d / "copy", {"uuid": "source-uuid"}, 0, "d"))
        self.assertNotEqual(u, regioncrop.spiral_patch_uuid(src, {"uuid": "source-uuid"}, 1, "d"))

    def test_a_source_erosion_override_is_what_the_check_uses(self):
        """meta.json's spiral_patch_erode_cells reaches every patch, and villa's loader erodes by it instead of its
        1-cell default (tifxyz.py Patch.erosion_cells), so the check must use it too: a 4-row strip survives 1 cell
        but not 5, and is then not written."""
        xyz, valid = grid()
        rp = self.d / "sc.json"
        rp.write_text(json.dumps(report(band(20) + band(26))))          # leaves a 4-row strip, rows 22 to 25
        tiny = regioncrop.merged({"regions": {"min_area_cm2": 0.0001}}, selfcross__dilate=0)
        plain = write(self.d / "plain.tifxyz", xyz, valid)
        rec = regioncrop.crop(plain, None, selfcross=rp, voxel_um=UNIT, spiral_patches=self.d / "vp1", params=tiny)
        strip = [r["index"] for r in rec["regions"] if r["rows"] == [22, 26]]
        self.assertEqual(len(strip), 1)
        self.assertIn(strip[0], rec["spiral_patches"]["written"])       # 1 cell leaves a row of quads
        self.assertEqual(rec["spiral_patches"]["erode_cells"], 1)
        five = write(self.d / "five.tifxyz", xyz, valid, {"spiral_patch_erode_cells": 5})
        rec = regioncrop.crop(five, None, selfcross=rp, voxel_um=UNIT, spiral_patches=self.d / "vp5", params=tiny)
        sp = rec["spiral_patches"]
        self.assertEqual(sp["erode_cells"], 5)
        self.assertIn("spiral_patch_erode_cells", sp["erode_from"])
        self.assertEqual(sp["dropped"], strip)
        self.assertEqual(len(sp["written"]), 2)
        for r in rec["regions"]:
            self.assertEqual(r["spiral_check"]["erode_cells"], 5)
            if r["index"] in sp["written"]:
                m = json.loads((Path(r["spiral_patch"]) / "meta.json").read_text())
                self.assertEqual(m["spiral_patch_erode_cells"], 5)      # villa erodes this patch by 5
                self.assertIsNotNone(self.villa_load(r["spiral_patch"]))
        bad = write(self.d / "bad.tifxyz", xyz, valid, {"spiral_patch_erode_cells": "a lot"})
        with self.assertRaises(regioncrop.CropError):
            regioncrop.crop(bad, None, selfcross=rp, voxel_um=UNIT, spiral_patches=self.d / "vpb", params=tiny)
        self.assertFalse((self.d / "vpb").exists())

    @unittest.skipUnless(__import__("os").environ.get("VILLA_SPIRAL_FITTING"), "VILLA_SPIRAL_FITTING not set")
    def test_villas_own_loader_opens_the_patches(self):
        """With VILLA_SPIRAL_FITTING naming a villa spiral-fitting tree that imports (torch, einops, PIL), its own
        load_tifxyz and erode_patch_valid_region open every written patch."""
        import os
        sys.path.insert(0, os.environ["VILLA_SPIRAL_FITTING"])
        from tifxyz import load_tifxyz
        from spiral_helpers import erode_patch_valid_region
        xyz, valid = grid()
        src = write(self.d / "trace.tifxyz", xyz, valid)
        rp = self.d / "sc.json"
        rp.write_text(json.dumps(report(band(20))))
        vp = self.d / "verified_patches"
        rec = regioncrop.crop(src, None, selfcross=rp, voxel_um=UNIT, spiral_patches=vp,
                              params=regioncrop.merged(SMALL, selfcross__dilate=0))
        for name in rec["spiral_patches"]["written"]:
            r = rec["regions"][name]
            patch = load_tifxyz(r["spiral_patch"], z_range=(0, 100))
            self.assertIsNotNone(patch)
            self.assertTrue(erode_patch_valid_region(patch, 1))

    def test_vc3d_points_read_back_as_point_collections(self):
        from kit import villafmt
        src, rp, xyz = self.source()
        pts = self.d / "pieces.json"
        rec = regioncrop.crop(src, None, selfcross=rp, voxel_um=UNIT, vc3d_points=pts, max_points=12,
                              params=regioncrop.merged(SMALL, selfcross__dilate=0))
        doc = json.loads(pts.read_text())
        self.assertEqual(doc["vc_pointcollections_json_version"], villafmt.VC3D_POINTS_VERSION)
        names = [c["name"] for c in doc["collections"].values()]
        self.assertEqual(names, ["trace-r00", "trace-r01", "trace-cuts"])
        points, fmt = villafmt.read_seeds(pts)                         # VC3D's PointCollections rules
        self.assertEqual(len(points), rec["vc3d_points"]["points"])
        for r, c in zip(rec["regions"], list(doc["collections"].values())[:2]):
            first = c["points"]["1"]["p"]
            r0, r1 = r["rows"]
            self.assertTrue(8 + 4 * r0 <= first[1] <= 8 + 4 * (r1 - 1))     # the anchor lies in its piece
            self.assertLessEqual(len(c["points"]), 13)                       # anchor plus max_points
        cuts = list(doc["collections"].values())[2]["points"].values()
        self.assertTrue(all(abs(p["p"][1] - (8 + 4 * 20.5)) < 1e-6 for p in cuts))   # the band's quad centres
        self.assertEqual(villafmt.read_seeds(pts, "trace-cuts")[0][0][2], 32.0)

    def test_the_command_writes_the_community_outputs_without_a_piece_folder(self):
        from kit import cli
        src, rp, _ = self.source()
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = cli.main(["meshqa", "crop", str(src), "--selfcross", str(rp), "--voxel-um", str(UNIT),
                             "--dilate", "0", "--min-area-cm2", "0.001", "--spiral-patches", str(self.d / "vp"),
                             "--vc3d-points", str(self.d / "p.json")])
        self.assertEqual(code, 0, e.getvalue())
        self.assertIn("spiral patches: 2 written", o.getvalue())
        self.assertIn("VC3D points: 3 collections", o.getvalue())
        self.assertEqual(len(list((self.d / "vp").iterdir())), 2)

    def test_the_command(self):
        from kit import cli
        src, rp, _ = self.source()
        out = self.d / "cmd"

        def run(*argv):
            o, e = io.StringIO(), io.StringIO()
            with redirect_stdout(o), redirect_stderr(e):
                code = cli.main(["meshqa", "crop", *argv])
            return code, o.getvalue(), e.getvalue()

        code, o, _ = run(str(src), "--dry-run", "--selfcross", str(rp), "--voxel-um", str(UNIT), "--dilate", "0",
                         "--min-area-cm2", "0.001", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(o)["regions"]), 2)
        self.assertFalse(out.exists())
        code, o, _ = run(str(src), str(out), "--selfcross", str(rp), "--voxel-um", str(UNIT), "--min-area-cm2",
                         "0.001", "--record", str(self.d / "rec.json"))
        self.assertEqual(code, 0)
        self.assertIn("whole trace: 20 crossings", o)
        self.assertEqual(len(list(out.iterdir())), 2)
        self.assertTrue((self.d / "rec.json").is_file())
        # nothing above the minimum area: exit 3; no output folder and no --dry-run: exit 2
        self.assertEqual(run(str(src), "--dry-run", "--selfcross", str(rp), "--voxel-um", str(UNIT),
                             "--min-area-cm2", "5")[0], 3)
        code, _, e = run(str(src), "--selfcross", str(rp))
        self.assertEqual(code, 2)
        self.assertIn("give an output folder", e)
        # no voxel size anywhere: refused rather than guessed
        code, _, e = run(str(src), "--dry-run", "--selfcross", str(rp))
        self.assertEqual(code, 2)
        self.assertIn("voxel size", e)

    def test_ct_and_prediction_by_location(self):
        ct, pred = volumes()
        from kit import switchfix
        xyz, valid = grid()
        xyz[10:21, 10:21, 2] += 7.0
        src = write(self.d / "air.tifxyz", xyz, valid)
        samplers = {"CT": switchfix.ArraySampler(ct), "PRED": switchfix.ArraySampler(pred)}
        with mock.patch.object(switchfix, "open_prediction", lambda loc, *a, **k: samplers[loc]):
            rec = regioncrop.crop(src, None, ct="CT", prediction="PRED", voxel_um=UNIT, write=False,
                                  params=regioncrop.merged(SMALL, seating__fail=["not seated"],
                                                           off_sheet__min_cells=25))
        self.assertEqual(rec["seating"]["verdicts"]["not seated"], 1)
        self.assertEqual(rec["off_sheet"]["cut_blob_vertices"], 121)
        self.assertEqual(rec["measured"], {"selfcross": False, "seating": True, "off_sheet": True})
        self.assertEqual(len(rec["regions"]), 1)
        self.assertIsNone(rec["whole_trace"]["transverse"])
        # the frozen settings: seating reported but not cut, no blob cut; the patch (7 % of the vertices off the
        # sheet) stays, and the same window moved half a pitch (all of it off) is rejected whole
        with mock.patch.object(switchfix, "open_prediction", lambda loc, *a, **k: samplers[loc]):
            rec = regioncrop.crop(src, None, ct="CT", prediction="PRED", voxel_um=UNIT, write=False,
                                  params=regioncrop.merged(SMALL))
            self.assertEqual((rec["cut_vertices"]["any"], len(rec["regions"])), (0, 1))
            moved = xyz.copy()
            moved[..., 2] += 7.0
            src2 = write(self.d / "moved.tifxyz", moved, valid)
            rec = regioncrop.crop(src2, None, prediction="PRED", voxel_um=UNIT, write=False,
                                  params=regioncrop.merged(SMALL))
        self.assertEqual((len(rec["regions"]), rec["dropped_off_sheet"]["pieces"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
