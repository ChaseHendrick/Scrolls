"""seed_check and trim (kit/vc3d_prep.py, kit/vc3d_prep_tools.py), and trace's seed check, on fake volumes."""

import json
import unittest
from pathlib import Path
from unittest import mock

from test_vc3d_agent import Base
import vc3d_fakes as fakes

from kit import vc3d_agent, vc3d_io, vc3d_prep_tools

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


def ct_half(z, y, x):
    """CT with papyrus (180) on a sheet at z 30 to 34 over air (40), and nothing (0) where x >= 24."""
    if x >= 24:
        return 0
    return 180 if 30 <= z <= 34 else 40


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestSeedCheck(Base):
    def test_on_off_and_nearest(self):
        vol = self.volume(fakes.sheet)
        on = self.call("seed_check", {"volume": str(vol), "seed": [24, 24, 32]})
        self.assertTrue(on["ok"] and on["on_prediction"])
        self.assertEqual(on["value"], 200.0)
        off = self.call("seed_check", {"volume": str(vol), "seed": [24, 24, 28]})
        self.assertFalse(off["ok"] or off["on_prediction"])
        self.assertEqual((off["nearest_on"], off["nearest_distance"]), ([24, 24, 31], 3.0))
        far = self.call("seed_check", {"volume": str(vol), "seed": [24, 24, 8], "radius": 4})
        self.assertIsNone(far["nearest_on"])
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("seed_check", {"volume": str(vol), "seed": [24, 24, 400]})

    def test_ct_papyrus_air_and_outside(self):
        vol = self.volume(fakes.sheet)
        ct = self.volume(ct_half, name="ct.zarr")
        on = self.call("seed_check", {"volume": str(vol), "seed": [12, 24, 32], "ct": str(ct)})
        self.assertEqual(on["ct"]["verdict"], "papyrus")
        self.assertTrue(on["ok"])
        outside = self.call("seed_check", {"volume": str(vol), "seed": [40, 24, 32], "ct": str(ct)})
        self.assertEqual(outside["ct"]["verdict"], "air")
        self.assertFalse(outside["ok"])    # on the prediction but over no CT: the control the check must catch
        flat = self.volume(lambda z, y, x: 90, name="flat.zarr")
        unclear = self.call("seed_check", {"volume": str(vol), "seed": [12, 24, 32], "ct": str(flat)})
        self.assertEqual(unclear["ct"]["verdict"], "unclear")
        self.assertTrue(unclear["ok"])

    def test_unreadable_chunk_is_a_tool_error(self):
        vol = self.volume(fakes.sheet)
        (vol / "0" / "0" / "0" / "0").write_bytes(b"not a chunk")
        with self.assertRaisesRegex(vc3d_agent.ToolError, "seed check: .*seed_check false"):
            self.call("seed_check", {"volume": str(vol), "seed": [8, 8, 8]})

    def test_snap_rechecks_ct_at_effective_seed(self):
        vol = self.volume(fakes.sheet)
        ct = self.volume(ct_half, name="ct.zarr")
        requested = [12, 24, 28]
        result = self.call("trace", {"volume": str(vol), "ct": str(ct), "seed": requested,
                                     "snap_seed": True})
        check = result["seed_check"]
        self.assertEqual(check["seed"], [12, 24, 31])
        self.assertEqual(check["moved_from"], requested)
        self.assertTrue(check["ok"] and check["on_prediction"])
        self.assertEqual(check["ct"]["verdict"], "papyrus")
        self.assertEqual(check["before_snap"]["seed"], requested)
        self.assertEqual(check["before_snap"]["ct"]["verdict"], "air")
        self.assertFalse(check["before_snap"]["on_prediction"])
        self.assertEqual(result["surfaces"][0]["bbox_xyz"][0][2], 31.0)

    def test_snap_into_ct_air_is_rejected_before_tracer(self):
        vol = self.volume(fakes.sheet)
        ct = self.volume(lambda z, y, x: 180 if 26 <= z <= 29 else 40, name="ct.zarr")
        original = self.call("seed_check", {"volume": str(vol), "ct": str(ct), "seed": [12, 24, 28]})
        self.assertEqual(original["ct"]["verdict"], "papyrus")
        with mock.patch.object(vc3d_agent, "run_logged", return_value=(0, 0.0)) as tracer:
            with self.assertRaisesRegex(vc3d_agent.ToolError, r"seed \[12, 24, 31\] is on air"):
                self.call("trace", {"volume": str(vol), "ct": str(ct), "seed": [12, 24, 28],
                                    "snap_seed": True})
            tracer.assert_not_called()

    def test_snap_recheck_failure_does_not_resnap(self):
        vol = self.volume(fakes.sheet)
        original = self.call("seed_check", {"volume": str(vol), "seed": [12, 24, 28]})
        changed = dict(original, seed=[12, 24, 31], nearest_on=[12, 24, 44])
        with mock.patch.object(vc3d_prep_tools, "check_seed", side_effect=[original, changed]) as checker, \
                mock.patch.object(vc3d_agent, "run_logged", return_value=(0, 0.0)) as tracer:
            with self.assertRaisesRegex(vc3d_agent.ToolError, "off the surface prediction"):
                self.call("trace", {"volume": str(vol), "seed": [12, 24, 28], "snap_seed": True})
            self.assertEqual(checker.call_count, 2)
            tracer.assert_not_called()

    def test_unreadable_snap_recheck_stops_before_tracer(self):
        vol = self.volume(fakes.sheet)
        original = self.call("seed_check", {"volume": str(vol), "seed": [12, 24, 28]})
        with mock.patch.object(vc3d_prep_tools, "check_seed",
                               side_effect=[original, vc3d_agent.ToolError("seed check: unreadable snapped CT")]) as checker, \
                mock.patch.object(vc3d_agent, "run_logged", return_value=(0, 0.0)) as tracer:
            with self.assertRaisesRegex(vc3d_agent.ToolError, "unreadable snapped CT"):
                self.call("trace", {"volume": str(vol), "seed": [12, 24, 28], "snap_seed": True})
            self.assertEqual(checker.call_count, 2)
            tracer.assert_not_called()

    def test_on_prediction_seed_is_checked_once_without_snap(self):
        vol = self.volume(fakes.sheet)
        with mock.patch.object(vc3d_prep_tools, "check_seed", wraps=vc3d_prep_tools.check_seed) as checker:
            result = self.call("trace", {"volume": str(vol), "seed": [12, 24, 32], "snap_seed": True})
            checker.assert_called_once()
        self.assertEqual(result["seed_check"]["seed"], [12, 24, 32])
        self.assertNotIn("before_snap", result["seed_check"])
        self.assertNotIn("moved_from", result["seed_check"])

    def test_trace_refuses_snaps_or_skips(self):
        vol = self.volume(fakes.sheet)
        with self.assertRaisesRegex(vc3d_agent.ToolError, "off the surface prediction.*24, 24, 31"):
            self.call("trace", {"volume": str(vol), "seed": [24, 24, 28]})
        snapped = self.call("trace", {"volume": str(vol), "seed": [24, 24, 28], "snap_seed": True})
        self.assertEqual(snapped["seed_check"]["moved_from"], [24, 24, 28])
        self.assertEqual(snapped["seed_check"]["seed"], [24, 24, 31])
        self.assertTrue(snapped["seed_check"]["ok"])
        self.assertNotIn("ct", snapped["seed_check"])
        self.assertEqual(snapped["surfaces"][0]["bbox_xyz"][0][2], 31.0)   # the fake traces at the seed's z
        skipped = self.call("trace", {"volume": str(vol), "seed": [24, 24, 28], "seed_check": False})
        self.assertNotIn("seed_check", skipped)
        self.assertEqual(skipped["surfaces"][0]["bbox_xyz"][0][2], 28.0)
        ct = self.volume(ct_half, name="ct.zarr")
        with self.assertRaisesRegex(vc3d_agent.ToolError, "on air"):
            self.call("trace", {"volume": str(vol), "seed": [40, 24, 32], "ct": str(ct)})


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestPhantoms(Base):
    def test_edge_halo_and_beyond(self):
        chunk = (16, 16, 16)
        pred = fakes.write_group(self.d / "pred.zarr", [64, 64, 64], fakes.sheet, chunk=chunk)
        ct = fakes.write_group(self.d / "ct.zarr", [64, 64, 64], ct_half, chunk=chunk)   # zero where x >= 24
        res = self.call("phantoms", {"volume": str(pred), "ct": str(ct)})
        # 9 planes of 64 x 64 at or above 128; x 24 to 63 (40 columns) have no CT
        self.assertEqual((res["prediction_voxels"], res["phantom_voxels"]), (9 * 64 * 64, 9 * 64 * 40))
        self.assertEqual(res["phantom_fraction"], 0.625)
        # x chunk 1 holds the mask edge, chunk 2 touches it, chunk 3 is two chunks from any CT
        self.assertEqual(res["phantom_cells"], {"edge": 8, "halo": 8, "beyond": 8})
        self.assertEqual({tuple(c[2]) for c in res["halo_cells"]}, {(32, 48)})
        self.assertEqual({tuple(c[2]) for c in res["beyond_cells"]}, {(48, 64)})
        self.assertIn("frame", res["warning"])
        boxed = self.call("phantoms", {"volume": str(pred), "ct": str(ct), "box": [[0, 64], [0, 64], [32, 48]]})
        self.assertEqual(boxed["phantom_cells"], {"edge": 0, "halo": 8, "beyond": 0})   # reads CT past the box

    def test_cells_are_level0_chunks_at_any_level(self):
        pred = fakes.write_group(self.d / "pred.zarr", [64, 64, 64], fakes.sheet, chunk=(16, 16, 16), levels=2,
                                 binned="zyx")
        ct = fakes.write_group(self.d / "ct.zarr", [64, 64, 64], ct_half, chunk=(16, 16, 16), levels=2, binned="zyx")
        res = self.call("phantoms", {"volume": str(pred), "ct": str(ct), "level": 1})
        self.assertEqual((res["cell_zyx"], res["ct_level"]), ([8, 8, 8], 1))     # one level-0 chunk is 8 voxels here
        self.assertEqual(res["phantom_cells"], {"edge": 8, "halo": 8, "beyond": 8})

    def test_full_ct_has_none_and_grids_must_match(self):
        pred = fakes.write_group(self.d / "pred.zarr", [64, 64, 64], fakes.sheet, chunk=(16, 16, 16))
        ramp = self.volume(fakes.ramp, name="full.zarr")
        full = self.call("phantoms", {"volume": str(pred), "ct": str(ramp)})
        self.assertEqual((full["phantom_voxels"], full["phantom_cells"]), (0, {"edge": 0, "halo": 0, "beyond": 0}))
        self.assertNotIn("warning", full)
        small = fakes.write_group(self.d / "small.zarr", [32, 64, 64], fakes.ramp)
        with self.assertRaisesRegex(vc3d_agent.ToolError, "one voxel grid"):
            self.call("phantoms", {"volume": str(pred), "ct": str(small)})
        with self.assertRaisesRegex(vc3d_agent.ToolError, "max_chunks"):
            self.call("phantoms", {"volume": str(pred), "ct": str(ramp), "level": 0, "max_chunks": 8})


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestFrame(Base):
    def test_picks_the_frame_the_mesh_seats_in(self):
        vol = self.volume(fakes.sheet)              # sheet at z 32, neighbours at 20 and 44
        surf = self.surface()                       # plane at z 32
        shifted = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 6]]
        res = self.call("frame", {"surface": str(surf), "half_layers": 8,
                                  "candidates": [{"volume": str(vol), "affine": shifted, "label": "z + 6"}],
                                  "volumes": [str(vol)], "scales": [0.5, 1, 2]})
        self.assertEqual((res["best"]["scale_segmentation"], res["best"].get("affine")), (1.0, None))
        self.assertTrue(res["clear"])
        self.assertEqual(res["best"]["verdict"], "seated")
        by = {(r.get("label"), r["scale_segmentation"]): r for r in res["candidates"]}
        self.assertEqual(by[(None, 2.0)]["verdict"], "outside the volume")    # z 64 is past the end
        self.assertLess(by[("z + 6", 1.0)]["score"], 0)                        # the control: off the sheet
        self.assertEqual(res["per_volume"][str(vol)]["best"], "x1")

    def test_a_frame_mostly_over_ct_zero_is_not_scored(self):
        surf = self.surface()                       # x 8 to 40; ct_half is zero from x 24
        res = self.call("frame", {"surface": str(surf), "half_layers": 8,
                                  "candidates": [{"volume": str(self.volume(ct_half, name="ct.zarr"))}],
                                  "volumes": [str(self.volume(fakes.sheet))], "scales": [1]})
        off = [r for r in res["candidates"] if r["volume"].endswith("ct.zarr")][0]
        self.assertEqual((off["verdict"], off["relative_score"], off["score"]), ("mostly off the CT", -1.0, -1.0))
        self.assertTrue(res["best"]["volume"].endswith("vol.zarr"))

    def test_seats_nowhere_is_not_clear(self):
        surf = self.surface(z=26)                   # between sheets
        res = self.call("frame", {"surface": str(surf), "half_layers": 4, "volumes": [str(self.volume(fakes.sheet))],
                                  "scales": [1, 0.5]})
        self.assertFalse(res["clear"])
        self.assertIn("no candidate", res["why"])
        with self.assertRaisesRegex(vc3d_agent.ToolError, "at least two"):
            self.call("frame", {"surface": str(surf), "volumes": [str(self.volume(fakes.sheet, name="v2.zarr"))],
                                "scales": [1]})

    def test_catalog_candidates_include_transforms(self):
        from test_vc3d_catalog import CATALOG
        from kit import vc3d_prep_tools
        got = vc3d_prep_tools.catalog_candidates(vc3d_agent, CATALOG, "V1", [1.0, 2.0])
        self.assertEqual([c.get("scale_segmentation") for c in got], [1.0, 2.0, None])
        self.assertTrue(got[2]["volume"].endswith("V2-2.4um.zarr/") or got[2]["volume"].endswith("V2-2.4um.zarr"))
        self.assertEqual(got[2]["affine"][0], [2, 0, 0, 1])
        with self.assertRaises(vc3d_agent.ToolError):
            vc3d_prep_tools.catalog_candidates(vc3d_agent, CATALOG, "V9", [1.0])


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestTrim(Base):
    def test_trims_over_zero_and_keeps_the_original(self):
        surf = self.surface()                      # 9 x 9 vertices at x = 8 + 4 c, z = 32
        ct = self.volume(ct_half, name="ct.zarr")  # zero where x >= 24, so columns 4 to 8
        before = (surf / "x.tif").read_bytes()
        res = self.call("trim", {"surface": str(surf), "ct": str(ct), "crop": False})
        self.assertEqual((res["valid_vertices"], res["trimmed_vertices"], res["kept_vertices"]), (81, 45, 36))
        self.assertEqual((surf / "x.tif").read_bytes(), before)
        out = Path(res["out"])
        x = vc3d_io.read_tiff(out / "x.tif").floats()
        kept = [v for v in x if v != -1]
        self.assertEqual((len(kept), max(kept)), (36, 20.0))
        meta = json.loads((out / "meta.json").read_text())
        self.assertEqual(meta["bbox"][1][0], 20.0)
        grown = self.call("trim", {"surface": str(surf), "ct": str(ct), "dilate": 1, "crop": False})
        self.assertEqual(grown["trimmed_vertices"], 54)
        none = self.call("trim", {"surface": str(surf), "ct": str(self.volume(fakes.sheet, name="full.zarr")),
                                  "crop": False})
        self.assertEqual(none["trimmed_vertices"], 0)

    def test_trim_notes_a_surface_mostly_off_the_scan(self):
        surf = self.surface()
        ct = self.volume(lambda z, y, x: 0 if x >= 12 else 100, name="ct.zarr")
        res = self.call("trim", {"surface": str(surf), "ct": str(ct)})
        self.assertGreater(res["trimmed_fraction"], 0.5)
        self.assertIn("frame", res["note"])
        self.assertIn("skipped", res["crop"])     # the fake bin has no vc_tifxyz_trim

    def test_trim_refuses_to_overwrite_the_surface(self):
        surf = self.surface()
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("trim", {"surface": str(surf), "ct": str(self.volume(ct_half, name="ct.zarr")),
                               "out": str(surf)})


MERGE_FAKE = fakes.PRELUDE + r'''
parent = Path(opt("--parent"))
meta = json.loads((parent / "meta.json").read_text())
meta["merged_child"] = opt("--child")
(parent / "meta.json").write_text(json.dumps(meta))
print("[6/6] done")
'''


class TestVolumeMetaAndMerge(Base):
    def test_volume_meta_writes_once(self):
        vol = self.volume(fakes.sheet)
        res = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})
        self.assertTrue(res["written"])
        meta = json.loads((vol / "meta.json").read_text())
        self.assertEqual((meta["type"], meta["width"], meta["height"], meta["slices"], meta["voxelsize"]),
                         ("vol", 64, 64, 64, 2.4))
        again = self.call("volume_meta", {"volume": str(vol), "voxel_um": 9.0})
        self.assertEqual((again["written"], again["existing"], again["meta"]["voxelsize"]), (False, "meta.json", 2.4))
        self.assertNotIn("villa_refuses", again)

    def test_volume_meta_writes_beside_a_metadata_json_villa_refuses(self):
        # The published surface predictions carry a metadata.json with no "scan" key, which villa throws on
        # (core/src/Volume.cpp 1037-1040); villa reads meta.json first, so one beside it opens the volume.
        vol = self.volume(fakes.sheet)
        published = json.dumps({"kind": "surface prediction", "model": "m7"})
        (vol / "metadata.json").write_text(published)
        res = self.call("volume_meta", {"volume": str(vol), "voxel_um": 9.362})
        self.assertEqual((res["written"], res["existing"]), (True, "metadata.json"))
        self.assertIn("no 'scan' key", res["villa_refuses"])
        self.assertEqual((vol / "metadata.json").read_text(), published)
        meta = json.loads((vol / "meta.json").read_text())
        self.assertEqual((meta["width"], meta["height"], meta["slices"], meta["voxelsize"]), (64, 64, 64, 9.362))
        again = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})
        self.assertEqual((again["written"], again["existing"]), (False, "meta.json"))
        self.assertNotIn("villa_refuses", again)
        # A metadata.json with "scan" whose sizes are not level 0's (a crop under its source's file) is refused too.
        crop = self.volume(fakes.sheet, name="crop.zarr")
        (crop / "metadata.json").write_text(json.dumps(
            {"scan": {"type": "vol", "uuid": "s", "width": 6621, "height": 6621, "slices": 20974}}))
        res = self.call("volume_meta", {"volume": str(crop), "voxel_um": 9.362})
        self.assertTrue(res["written"])
        self.assertIn("level 0's shape is [64, 64, 64]", res["villa_refuses"])

    def test_volume_meta_leaves_a_metadata_json_villa_opens(self):
        vol = self.volume(fakes.sheet)
        doc = {"scan": {"type": "vol", "uuid": "s", "width": 64, "height": 64, "slices": 64, "voxelsize": 9.362}}
        (vol / "metadata.json").write_text(json.dumps(doc))
        res = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})
        self.assertEqual((res["written"], res["existing"], res["meta"]), (False, "metadata.json", doc))
        self.assertNotIn("villa_refuses", res)
        self.assertNotIn("note", res)
        self.assertFalse((vol / "meta.json").exists())
        # Its byte order mark is skipped, as villa skips it, so the file is read and left alone, not overridden
        (vol / "metadata.json").write_text("\ufeff" + json.dumps(doc))
        bom = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})
        self.assertEqual((bom["written"], bom["meta"]), (False, doc))
        self.assertNotIn("villa_refuses", bom)
        self.assertFalse((vol / "meta.json").exists())

    def test_volume_meta_notes_a_metadata_json_villa_opens_with_no_voxel_size(self):
        # villa opens it, warns, and uses 0 (Volume.cpp 67-82): the tracer then cannot apply min_area_cm
        vol = self.volume(fakes.sheet)
        doc = {"scan": {"type": "vol", "uuid": "s", "width": 64, "height": 64, "slices": 64, "voxelsize": 0}}
        (vol / "metadata.json").write_text(json.dumps(doc))
        res = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})
        self.assertEqual((res["written"], res["existing"]), (False, "metadata.json"))
        self.assertNotIn("villa_refuses", res)
        self.assertIn("no voxel size", res["note"])
        self.assertIn("write a meta.json beside it by hand", res["note"])
        self.assertFalse((vol / "meta.json").exists())

    def test_villa_voxel_size_follows_its_resolver(self):
        size = vc3d_prep_tools.villa_voxel_size
        record = {"tomo": {"acquisition": {"detector": {"samplePixelSize": 0.0024}}}}

        def rec(mm):
            return {"tomo": {"acquisition": {"detector": {"samplePixelSize": mm}}}}
        for doc, want in [
                ({"scan": rec(0.0024), **rec(0.009)}, 2.4),                       # the scan's record before the root's
                ({"scan": {}, "source": {"metadata": rec(0.0024), "resolution": "32"}}, None),  # levels stop at 31
                ({"scan": {"voxelsize": "2_4"}}, None),                           # stod stops at the underscore
                ({"voxelsize": 7.91, "scan": {"voxelsize": 9.0}}, 7.91),          # the root first
                ({"voxelsize": 0, "pixel_size_um": "2.4", "scan": {}}, 2.4),      # a string holding a number
                ({"voxel_size_um": True, "scan": {"voxelsize": 9.0}}, 9.0),       # a boolean is not a number
                ({"scan": {"voxelsize": 9.0, **record}}, 9.0),                    # scan.voxelsize over the record
                ({"scan": {"voxelsize": -1, **record}}, 2.4),                     # the record, in mm
                (dict(record, scan={}), 2.4),                                     # the record at the root
                ({"scan": {}, "source": {"metadata": {"scan": record}, "resolution": "2"}}, 9.6),
                ({"scan": {}, "source": {"metadata": record, "resolution": 1.5}}, None),   # no whole level
                ({"scan": {}, "source": {"metadata": record}}, None),                      # no level at all
                ({"scan": {"voxelsize": "nine"}}, None),
                ({"scan": {}}, None),
                ([], None)]:
            with self.subTest(doc=doc):
                got = size(doc)
                self.assertTrue(got == want if want is None else abs(got - want) < 1e-9, got)

    def test_volume_meta_reports_but_keeps_a_meta_json_villa_refuses(self):
        vol = self.volume(fakes.sheet)
        (vol / "meta.json").write_text('{"type": "vol", "voxelsize": 2.4}')
        res = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})
        self.assertEqual((res["written"], res["existing"]), (False, "meta.json"))
        self.assertIn("lacks uuid, width, height, slices", res["villa_refuses"])
        self.assertIn("fixed by hand", res["note"])
        self.assertEqual((vol / "meta.json").read_text(), '{"type": "vol", "voxelsize": 2.4}')
        (vol / "meta.json").write_text("not json")
        broken = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})
        self.assertEqual((broken["written"], broken["meta"], broken["villa_refuses"]),
                         (False, None, "meta.json is not JSON"))

    def test_a_number_villa_cannot_hold_makes_a_file_not_json(self):
        self.assertEqual(vc3d_prep_tools.villa_json('{"voxelsize": 18446744073709551615}')["voxelsize"], 2 ** 64 - 1)
        self.assertEqual(vc3d_prep_tools.villa_json('{"v": ' + "1" + "0" * 30 + "}")["v"], 1e30)   # read as a double
        for text in ('{"voxelsize": 1e400}', '{"voxelsize": -1e400}', '{"v": 1' + "0" * 400 + "}"):
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):
                vc3d_prep_tools.villa_json(text)
        vol = self.volume(fakes.sheet)
        doc = {"type": "vol", "uuid": "u", "width": 64, "height": 64, "slices": 64,
               "scan": {"voxelsize": int("1" + "0" * 400)}}
        (vol / "metadata.json").write_text(json.dumps(doc))
        res = self.call("volume_meta", {"volume": str(vol), "voxel_um": 2.4})       # refused, not a crash
        self.assertEqual((res["written"], res["villa_refuses"]), (True, "metadata.json is not JSON"))

    def test_villa_refuses_each_reason_and_passes_a_good_file(self):
        good = {"type": "vol", "uuid": "u", "format": "zarr", "width": 60, "height": 64, "slices": 64}
        unformatted = {k: v for k, v in good.items() if k != "format"}
        head = {"shape": [64, 64, 64], "chunks": [32, 32, 32]}
        check = vc3d_prep_tools.villa_refuses
        self.assertIsNone(check("meta.json", json.dumps(good), head))   # 4 short of a chunk: padding villa allows
        self.assertIsNone(check("metadata.json", json.dumps({"scan": good}), head))
        self.assertIsNone(check("metadata.json", json.dumps(dict(good, scan={"voxelsize": 9.4})), head))
        self.assertIsNone(check("meta.json", json.dumps(dict(good, width=6621))))   # no header: no shape check
        # scan overrides the root, as nlohmann's update does (Volume.cpp 1045)
        self.assertIsNone(check("metadata.json", json.dumps(dict(good, width=6621, scan={"width": 60})), head))
        # a metadata.json that names no format is read as zarr (1046-1048); a meta.json is not
        self.assertIsNone(check("metadata.json", json.dumps({"scan": unformatted}), head))
        self.assertIsNone(check("meta.json", "\ufeff" + json.dumps(good), head))   # villa skips a byte order mark
        for name, doc, why in [
                ("meta.json", json.dumps(unformatted), "meta.json has no format"),
                ("metadata.json", json.dumps({"scan": dict(good, format="tif")}), "format 'tif', not 'zarr'"),
                ("meta.json", json.dumps(dict(good, format=1)), "format 1 is not a string"),
                ("meta.json", json.dumps(dict(good, voxelsize=float("nan"))), "not JSON"),
                ("metadata.json", json.dumps({"scan": dict(good, voxelsize=float("inf"))}), "not JSON"),
                ("meta.json", json.dumps(dict(good, width=32)), "level 0's shape"),   # padded by one chunk exactly
                ("meta.json", "{", "not JSON"),
                ("meta.json", "[]", "not a JSON object"),
                ("metadata.json", json.dumps(good), "no 'scan' key"),
                ("metadata.json", json.dumps({"scan": 1}), "'scan' is not an object"),
                ("meta.json", json.dumps(dict(good, type="seg")), "type 'seg'"),
                ("metadata.json", json.dumps({"scan": dict(good, type=None)}), "type None"),
                ("meta.json", json.dumps({"type": "vol", "uuid": "u", "width": 64}), "lacks height, slices"),
                ("meta.json", json.dumps(dict(good, slices="64")), "slices '64' is not a number"),
                ("meta.json", json.dumps(dict(good, width=6621)), "level 0's shape"),
                ("meta.json", json.dumps(dict(good, width=30)), "level 0's shape")]:   # 34 over: a chunk or more
            with self.subTest(name=name, doc=doc):
                self.assertIn(why, check(name, doc, head) or "(villa_refuses gave None)")

    def test_merge_patch_works_on_a_copy(self):
        parent, child = self.surface(name="parent.tifxyz"), self.surface(z=33, name="child.tifxyz")
        with self.assertRaisesRegex(vc3d_agent.ToolError, "vc_merge_patch is not in"):
            self.call("merge_patch", {"parent": str(parent), "child": str(child)})
        exe = self.bin / "vc_merge_patch"
        exe.write_text(MERGE_FAKE)
        exe.chmod(0o755)
        before = (parent / "meta.json").read_text()
        res = self.call("merge_patch", {"parent": str(parent), "child": str(child)})
        self.assertEqual(res["exit"], 0)
        self.assertEqual((parent / "meta.json").read_text(), before)
        out = Path(res["out"])
        given = Path(json.loads((out / "meta.json").read_text())["merged_child"])
        self.assertEqual((given.name, given.parent.name), ("child.tifxyz", "child.tifxyz-ring"))
        ring = vc3d_io.read_tiff(given / "x.tif")
        self.assertEqual((ring.h, ring.w, ring.floats().count(-1.0)), (11, 11, 40))   # one invalid ring
        self.assertIn("ring", res["child_ring"])
        self.assertEqual(res["surface"]["valid_vertices"], 81)
        rimmed = fakes.write_tifxyz(self.d / "rimmed.tifxyz", lambda r, c: (-1, -1, -1) if r in (0, 8) or c in (0, 8)
                                    else (8.0 + 4 * c, 8.0 + 4 * r, 33))
        kept = self.call("merge_patch", {"parent": str(parent), "child": str(rimmed)})
        self.assertNotIn("child_ring", kept)
        self.assertEqual(json.loads((Path(kept["out"]) / "meta.json").read_text())["merged_child"], str(rimmed))
        with self.assertRaises(vc3d_agent.ToolError):
            self.call("merge_patch", {"parent": str(parent), "child": str(parent)})
        with self.assertRaisesRegex(vc3d_agent.ToolError, "exists"):
            self.call("merge_patch", {"parent": str(parent), "child": str(child), "out": str(out)})


MERGE_GRID_FAKE = fakes.PRELUDE + r'''
import shutil
grid = json.loads(Path(opt("--merge")).read_text())["rows"]
paths = Path(opt("--paths-dir"))
first = min(n for row in grid for n in row if n)
shutil.copytree(paths / first, paths / (first + "_merged"))
print("merged", grid)
'''


class TestMergeSurfaces(Base):
    def test_builds_the_layout_and_reports_the_merge(self):
        a, b = self.surface(name="a.tifxyz"), self.surface(z=33, name="b.tifxyz")
        with self.assertRaisesRegex(vc3d_agent.ToolError, "vc_merge_tifxyz is not in"):
            self.call("merge_surfaces", {"rows": [[str(a), str(b)]]})
        exe = self.bin / "vc_merge_tifxyz"
        exe.write_text(MERGE_GRID_FAKE)
        exe.chmod(0o755)
        res = self.call("merge_surfaces", {"rows": [[str(a), None], [str(b), None]]})
        self.assertEqual(res["exit"], 0)
        self.assertEqual(res["grid"], [["a.tifxyz", None], ["b.tifxyz", None]])
        out = Path(res["out"])
        self.assertEqual(json.loads((out / "merge.json").read_text()), {"rows": res["grid"]})
        self.assertTrue((out / "paths" / "a.tifxyz").is_symlink())
        (merged,) = res["surfaces"]
        self.assertEqual((Path(merged["path"]).name, merged["valid_vertices"]), ("a.tifxyz_merged", 81))
        self.assertEqual(sorted(p.name for p in self.d.iterdir() if p.name.endswith(".tifxyz")),
                         ["a.tifxyz", "b.tifxyz"])     # inputs untouched, nothing written beside them
        with self.assertRaisesRegex(vc3d_agent.ToolError, "at least two"):
            self.call("merge_surfaces", {"rows": [[str(a)]]})
        other = self.d / "x"
        other.mkdir()
        same_name = fakes.write_tifxyz(other / "a.tifxyz", fakes.plane(34))
        with self.assertRaisesRegex(vc3d_agent.ToolError, "share the folder name"):
            self.call("merge_surfaces", {"rows": [[str(a), str(same_name)]]})


@unittest.skipUnless(HAVE_NUMPY, "needs numpy")
class TestSeedHorizon(Base):
    """seed_check's opt-in horizon triage (villa PR #2047's shell classes), report only."""

    def triage(self, fn, seed, name):
        vol = self.volume(fn, name=name)
        return self.call("seed_check", {"volume": str(vol), "seed": seed, "horizon": True})

    def test_classes(self):
        layered = self.triage(lambda z, y, x: 200 if z % 4 < 2 else 0, [32, 32, 32], "layered.zarr")
        self.assertEqual(layered["horizon"]["class"], "HEALTHY")
        self.assertFalse(layered["horizon"]["edge"])
        blob = self.triage(lambda z, y, x: 200 if (z - 32) ** 2 + (y - 32) ** 2 + (x - 32) ** 2 < 81 else 0,
                           [32, 32, 32], "blob.zarr")
        self.assertEqual(blob["horizon"]["class"], "TRAPPED")
        self.assertTrue(blob["ok"])            # report only: the seed is on the prediction, so seed_check passes
        thin = self.triage(lambda z, y, x: 200 if z == 32 else 0, [32, 32, 32], "thin.zarr")
        self.assertEqual(thin["horizon"]["class"], "SPARSE_REGION")
        void = self.triage(lambda z, y, x: 0, [32, 32, 32], "void.zarr")
        self.assertEqual(void["horizon"]["class"], "SEED_VOID")
        self.assertFalse(void["ok"])

    def test_edge_and_off_by_default(self):
        near = self.triage(lambda z, y, x: 200 if z % 4 < 2 else 0, [32, 32, 10], "edge.zarr")
        self.assertTrue(near["horizon"]["edge"])
        self.assertEqual(near["horizon"]["distance_to_face"], 10)
        self.assertEqual(near["horizon"]["class"], "HEALTHY")   # the shells count only voxels inside the volume
        vol = self.volume(fakes.sheet)
        self.assertNotIn("horizon", self.call("seed_check", {"volume": str(vol), "seed": [24, 24, 32]}))

    def test_outer_shell_is_the_rest_of_the_cube(self):
        # A slab 15 voxels thick through the seed: the PR's statistic (last shell out to the cube's corners) gives
        # outer 0.38, under its 0.40 cut; a ball cut at 33 voxels would give 0.41 and call it HEALTHY.
        slab = self.triage(lambda z, y, x: 200 if 25 <= x < 40 else 0, [32, 32, 32], "slab.zarr")
        self.assertEqual(slab["horizon"]["class"], "TRAPPED")
        self.assertAlmostEqual(slab["horizon"]["outer"], 0.38, delta=0.01)


if __name__ == "__main__":
    unittest.main()
