"""kit labelxfer: published labels carried onto another surface's render canvas, on synthetic meshes and labels."""

import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from kit import cli

try:
    import numpy as np
    import scipy.spatial  # noqa: F401
    import tifffile
    import zarr
    from kit import labelxfer as lx
except ImportError:  # the core kit is standard library only
    np = tifffile = zarr = lx = None

VOXEL_UM = 100.0          # 2 mm is then 20 canvas pixels, so the displaced control fits a small canvas


def write_mesh(path, fn, rows, cols, scale, holes=()):
    """A tifxyz whose vertex (r, c) is fn(r, c) -> (x, y, z); holes are -1 as VC3D writes them."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    r, c = np.meshgrid(np.arange(rows, dtype=np.float64), np.arange(cols, dtype=np.float64), indexing="ij")
    xyz = np.stack(fn(r, c), -1).astype(np.float32)
    for hr, hc in holes:
        xyz[hr, hc] = -1
    for k, a in enumerate("xyz"):
        tifffile.imwrite(str(p / f"{a}.tif"), xyz[..., k])
    (p / "meta.json").write_text(json.dumps({"scale": [scale, scale], "format": "tifxyz", "type": "seg"}))
    return p


def bump(x):
    return 200.0 + 20.0 * np.sin(x / 100.0)


def published(r, c):
    """24 x 32 vertices 10 voxels apart (scale 0.1: a canvas pixel is a voxel), gently curved in z."""
    x = 20.0 + 10.0 * c
    return x, 20.0 + 10.0 * r, bump(x)


def write_labels(path, ink, sup):
    for name, data in (("inklabels", ink), ("supervision", sup)):
        g = zarr.open_group(str(Path(path) / f"{name}.zarr"), mode="w")
        g.create_array("2", data=(data.astype(np.uint8) * 255))
    return Path(path)


def blob_labels(seed=3, striped=False):
    """Labels at half the canvas resolution (120 x 160 for a 240 x 320 canvas): ink in 8 x 8 blocks (16 canvas
    pixels), or in stripes along the columns, which a shift along the columns cannot change."""
    if striped:
        ink = np.zeros((120, 160), bool)
        ink[(np.arange(120) // 6) % 2 == 0] = True
    else:
        ink = np.kron(np.random.default_rng(seed).random((15, 20)) > 0.6, np.ones((8, 8), bool))
    sup = np.zeros((120, 160), bool)
    sup[5:115, 5:155] = True
    return ink, sup


@unittest.skipIf(lx is None, "numpy, scipy, tifffile and zarr are needed for kit labelxfer")
class CanvasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def mesh(self, rows, cols, scale, **kw):
        return lx.read_mesh(write_mesh(self.root / f"m{rows}x{cols}-{scale}", published, rows, cols, scale, **kw))

    def test_canvas_size_is_vc_render_tifxyz_lround(self):
        self.assertEqual(lx.canvas_shape(self.mesh(24, 32, 0.1)), (240, 320))
        self.assertEqual(lx.canvas_shape(self.mesh(211, 238, 0.05)), (4220, 4760))   # w00's grid and canvas
        self.assertEqual(lx.canvas_shape(self.mesh(3, 5, 0.4)), (8, 13))              # 7.5 and 12.5 round up
        self.assertEqual(lx.canvas_shape(self.mesh(3, 7, 0.3)), (10, 23))             # 23.33 rounds down

    def test_pixel_to_grid_follows_the_centred_origin(self):
        m = self.mesh(24, 32, 0.1)
        gy, gx = lx.grid_of_pixel(m, np.array([0, 119.5, 239]), np.array([0, 159.5, 319]))
        np.testing.assert_allclose(gx, [0.05, 16.0, 31.95])
        np.testing.assert_allclose(gy, [0.05, 12.0, 23.95])
        # an exact canvas puts pixel C at (C + 0.5) * scale, which is what the fake render in vc3d_fakes uses
        C = np.arange(320)
        np.testing.assert_allclose(lx.grid_of_pixel(m, 0, C)[1], (C + 0.5) * 0.1)
        R, Cb = lx.pixel_of_grid(m, *lx.grid_of_pixel(m, np.arange(240)[:, None], C[None, :]))
        np.testing.assert_allclose(Cb, np.broadcast_to(C, Cb.shape), atol=1e-9)
        np.testing.assert_allclose(R, np.broadcast_to(np.arange(240)[:, None], R.shape), atol=1e-9)
        # the w00 grid, where spreading the grid evenly over the canvas (overlap.sample_grid) is off by pixels
        w = self.mesh(211, 238, 0.05)
        self.assertAlmostEqual(float(lx.grid_of_pixel(w, 0, 4759)[1]), 238 / 2 + 2379.5 * 0.05)

    def test_sampled_points_normals_and_rendered_pixels(self):
        m = self.mesh(24, 32, 0.1, holes=[(10, 10)])
        pts, nrm, ok = lx.sample_pixels(m, np.full(320, 60), np.arange(320))
        np.testing.assert_allclose(pts[ok, 0], 20.5 + np.arange(320)[ok], atol=1e-4)   # x = 20 + 10 * (C + 0.5) / 10
        self.assertTrue(np.allclose(np.linalg.norm(nrm[ok], axis=1), 1.0))
        mask = lx.rendered_mask(m)
        self.assertFalse(mask[:5].any() or mask[-5:].any() or mask[:, :5].any() or mask[:, -5:].any())  # border
        self.assertTrue(mask[5:-5, 5:-5][:50, :50].all())
        # vertex (10, 10) is canvas pixels 95 to 104; every bilinear cell touching it (90 to 109) and the four
        # vertices beside it, whose normals need it (85 to 94 and 105 to 114 along the cross), are not rendered
        self.assertFalse(mask[90:110, 90:110].any())
        self.assertFalse(mask[85:95, 95:105].any() or mask[105:115, 95:105].any() or mask[95:105, 85:95].any())
        self.assertTrue(mask[84, 100] and mask[87, 87] and mask[112, 112] and mask[150, 150])

    def test_bad_meshes_are_refused(self):
        p = write_mesh(self.root / "bad", published, 4, 4, 0.1)
        (p / "meta.json").write_text("{}")
        with self.assertRaises(lx.VerifyError):
            lx.read_mesh(p)
        with self.assertRaises(lx.VerifyError):
            lx.read_mesh(self.root / "missing")


@unittest.skipIf(lx is None, "numpy, scipy, tifffile and zarr are needed for kit labelxfer")
class CarryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pub = write_mesh(self.root / "pub.tifxyz", published, 24, 32, 0.1)
        self.ink, self.sup = blob_labels()
        self.labels = write_labels(self.root / "labels", self.ink, self.sup)

    def tearDown(self):
        self.tmp.cleanup()

    def trace(self, name, fn, rows, cols, scale):
        return write_mesh(self.root / f"{name}.tifxyz", fn, rows, cols, scale)

    def carry(self, trace, **kw):
        return lx.carry(trace, self.pub, self.labels, voxel_um=VOXEL_UM, **kw)

    def test_identity_and_displaced_checks_pass(self):
        res = lx.check(self.pub, self.labels, self.root / "check", voxel_um=VOXEL_UM, surface_shape=(240, 320))
        self.assertTrue(res["passes"], res)
        self.assertGreaterEqual(res["identity"]["coverage"], lx.IDENTITY_MIN_COVERAGE)
        self.assertEqual(res["identity"]["ink_agreement"], 1.0)
        self.assertEqual(res["identity"]["own_pixel_share"], 1.0)
        self.assertEqual([d["shift_px"] for d in res["displaced"]["directions"]],
                         [[0, 20], [20, 0], [0, -20], [-20, 0]])
        self.assertLessEqual(res["displaced"]["max_dice"], 1.0 - lx.DISPLACED_MIN_DROP)
        self.assertTrue((self.root / "check" / "record.json").is_file())

    def test_displaced_check_can_fail(self):
        """Ink in stripes along the columns: a shift along the columns moves nothing, so the control is not
        caught and the check fails, as it must."""
        ink, sup = blob_labels(striped=True)
        labels = write_labels(self.root / "striped", ink, sup)
        res = lx.check(self.pub, labels, voxel_um=VOXEL_UM)
        self.assertTrue(res["identity"]["passes"])
        self.assertFalse(res["displaced"]["passes"])
        self.assertFalse(res["passes"])
        self.assertEqual(res["displaced"]["max_dice"], 1.0)

    def test_identity_check_can_fail(self):
        """A sheet crumpled on a scale finer than the lattice: the tangent planes miss it by more than the gap
        tolerance, so its own labels do not come back and the identity check fails."""
        def crumpled(r, c):
            return 20.0 + c, 20.0 + r, 200.0 + 6.0 * np.sin(2 * math.pi * c / 9.0) * np.cos(2 * math.pi * r / 11.0)
        mesh = write_mesh(self.root / "crumpled.tifxyz", crumpled, 120, 160, 1.0)
        ink, sup = np.zeros((60, 80), bool), np.zeros((60, 80), bool)
        ink[10:50:4], sup[5:55, 5:75] = True, True
        labels = write_labels(self.root / "crumpled-labels", ink, sup)
        res = lx.check(mesh, labels, voxel_um=VOXEL_UM, lattice_px=12)
        self.assertLess(res["identity"]["coverage"], lx.IDENTITY_MIN_COVERAGE)
        self.assertFalse(res["passes"])

    def test_same_surface_on_another_grid_takes_the_labels_of_the_same_place(self):
        """The trace covers the same sheet with its own grid, 37 voxels along and with half the vertex spacing:
        its pixel C is the published pixel C + 37."""
        def shifted(r, c):
            x = 57.0 + 5.0 * c
            return x, 40.0 + 5.0 * r, bump(x)
        t = self.trace("shifted", shifted, 30, 40, 0.2)
        res = self.carry(t, surface_shape=(240, 320))
        a, rec = res["arrays"], res["record"]
        self.assertEqual(rec["trace_canvas"], [150, 200])
        lab = a["status"] == lx.LABELLED
        self.assertGreater(lab.sum(), 20000)
        rows, cols = np.indices(a["status"].shape)
        self.assertLessEqual(np.abs(a["src_col"][lab] - (cols[lab] + 37)).max(), 1)
        self.assertLessEqual(np.abs(a["src_row"][lab] - (rows[lab] + 20)).max(), 1)
        self.assertLess(float(np.nanmax(a["gap"][lab])), 0.5)
        # the carried ink is the published ink at the source pixels
        lr, lc = lx.labels_on_canvas(self.ink, self.sup, (240, 320))
        want = self.ink[lr[a["src_row"][lab]], lc[a["src_col"][lab]]]
        np.testing.assert_array_equal(a["ink"][lab], want)
        self.assertEqual(rec["ink_px"] + rec["background_px"], rec["labelled_px"])
        self.assertAlmostEqual(rec["labelled_cm2"], rec["labelled_px"] * (VOXEL_UM * 1e-4) ** 2, places=3)
        self.assertEqual(rec["share_refused_by_normal_test"], 0.0)

    def test_the_next_winding_gets_no_labels(self):
        """A sheet 12 voxels off (about the PHerc0841 pitch) is beyond the 4-voxel tolerance; one 2 voxels off is
        within it, its gap measured as 2 and its offset along the published normal one-signed."""
        for dz, carried in ((12.0, False), (2.0, True)):
            def lifted(r, c, dz=dz):
                x = 20.0 + 10.0 * c
                return x, 20.0 + 10.0 * r, bump(x) + dz
            res = self.carry(self.trace(f"lift{dz}", lifted, 24, 32, 0.1))
            a, rec = res["arrays"], res["record"]
            rendered = a["status"] != lx.NOT_RENDERED
            if carried:
                self.assertGreater(rec["labelled_px"], 0.9 * self.sup.sum() * 4 * 0.9)
                g = a["gap"][a["status"] == lx.LABELLED]
                self.assertTrue(np.all(np.abs(g - 2.0 * np.cos(np.arctan(0.2 * np.cos(0.0)))) < 0.25))
                off = a["offset"][a["status"] >= lx.UNSUPERVISED]
                self.assertTrue(np.all(np.sign(off) == np.sign(off[0])))
            else:
                self.assertEqual(rec["labelled_px"], 0)
                self.assertTrue(np.all(a["status"][rendered] == lx.NO_SURFACE))
                self.assertGreater(rec["gap_vox"]["percentiles"]["50"], 11.0)

    def test_a_crossing_sheet_is_refused_by_the_normal_test(self):
        """Planes through the published sheet's middle row: at 45 degrees the pixels near the crossing are within
        the gap tolerance but refused by the normal test; at 20 degrees they are carried."""
        for deg, refused in ((45.0, True), (20.0, False)):
            t = math.tan(math.radians(deg))
            def tilted(r, c, t=t):
                x = 20.0 + 10.0 * c
                return x, 20.0 + 10.0 * r, bump(x) + t * (10.0 * r - 120.0)
            res = self.carry(self.trace(f"tilt{deg}", tilted, 24, 32, 0.1))
            st, rec = res["arrays"]["status"], res["record"]
            if refused:
                self.assertGreater((st == lx.NORMAL_REFUSED).sum(), 500)
                self.assertEqual(rec["labelled_px"], 0)
                self.assertEqual(rec["share_refused_by_normal_test"], 1.0)
            else:
                self.assertEqual((st == lx.NORMAL_REFUSED).sum(), 0)
                self.assertGreater(rec["labelled_px"], 500)

    def test_a_wrong_published_canvas_is_refused(self):
        with self.assertRaises(lx.VerifyError):
            self.carry(self.pub, surface_shape=(240, 321))
        with self.assertRaises(lx.VerifyError):
            self.carry(self.pub, max_normal_deg=90)

    def test_write_and_load_legacy_names(self):
        """names="legacy" keeps the files written before 21 Oct 2026, which earlier runs and scripts read."""
        out = self.root / "x"
        self.carry(self.pub, out=out, names="legacy")
        names = {p.name for p in out.iterdir()}
        self.assertTrue({"transfer.npz", "inklabels.tif", "supervision.tif", "inklabels.zarr", "supervision.zarr",
                         "record.json"} <= names)
        self.assertFalse(any("_inklabels" in n or "supervision_mask" in n for n in names))
        rec, a = lx.load(out)
        self.assertEqual(len(rec["digest"]), 64)
        self.assertEqual(a["supervision"].dtype, bool)
        self.assertEqual(int(a["supervision"].sum()), rec["labelled_px"])
        self.assertEqual(tifffile.imread(str(out / "inklabels.tif")).dtype, np.uint8)
        self.assertEqual(zarr.open_array(str(out / "inklabels.zarr"), mode="r").ndim, 2)
        self.assertEqual(rec["villa"]["names"], "legacy")

    def test_load_reads_a_transfer_written_before_villa_names(self):
        """A record with no label_files (written before 21 Oct 2026) is read from inklabels.tif and
        supervision.tif; a record that names a missing file is refused."""
        out = self.root / "old"
        self.carry(self.pub, out=out, names="legacy")
        rec = json.loads((out / "record.json").read_text())
        rec.pop("label_files")
        rec.pop("villa")
        (out / "record.json").write_text(json.dumps(rec))
        rec2, a = lx.load(out)
        self.assertEqual(int(a["supervision"].sum()), rec2["labelled_px"])
        rec["label_files"] = {"inklabels": "gone_inklabels.tif", "supervision_mask": "supervision.tif"}
        (out / "record.json").write_text(json.dumps(rec))
        with self.assertRaises(lx.VerifyError):
            lx.load(out)


@unittest.skipIf(lx is None, "numpy, scipy, tifffile and zarr are needed for kit labelxfer")
class VillaNamesTest(unittest.TestCase):
    """The carried labels in villa's training names and label zarr layout (villa main 8aa507c12:
    vesuvius/src/vesuvius/ink_detection/data/segment.py:12-120, vesuvius/src/vesuvius/label_zarr.py:12-147,
    ink_detection/preprocessing/create_label_zarrs.py:188-583)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pub = write_mesh(self.root / "pub.tifxyz", published, 24, 32, 0.1)
        self.ink, self.sup = blob_labels()
        self.labels = write_labels(self.root / "labels", self.ink, self.sup)

        def shifted(r, c):
            x = 57.0 + 5.0 * c
            return x, 40.0 + 5.0 * r, bump(x)
        # a 30 x 40 grid at scale 0.2 gives a 150 x 200 canvas: odd halvings (75, 38, 19, 10, 5) test the rounding
        self.trace = write_mesh(self.root / "traces" / "w00-trace", shifted, 30, 40, 0.2)
        self.out = self.root / "train" / "w00-trace"
        self.rec = lx.carry(self.trace, self.pub, self.labels, self.out, voxel_um=VOXEL_UM, names="villa")["record"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_python_default_is_legacy_command_line_default_is_villa(self):
        """From Python, carry keeps the names written before 21 Oct 2026, which AutoPipeline's score.transfer (in
        kit/autopipe.py, pinned by live freezes) reads; `kit labelxfer carry` and
        `check` default to villa's names."""
        import argparse
        out = self.root / "pydefault"
        rec = lx.carry(self.trace, self.pub, self.labels, out, voxel_um=VOXEL_UM)["record"]
        self.assertEqual(rec["label_files"], {"inklabels": "inklabels.tif", "supervision_mask": "supervision.tif"})
        self.assertTrue((out / "inklabels.zarr").exists())
        p = argparse.ArgumentParser()
        lx.build_parser(p)
        for action in ("carry", "check"):
            args = p.parse_args([action] + (["T", "--from", "P"] if action == "carry" else ["M"])
                                + ["--labels", "L", "--out", "O", "--voxel-um", "7.91"])
            self.assertEqual((args.names, args.label_zarr), ("villa", True))

    def test_villa_names_for_the_trace_folder(self):
        names = {p.name for p in self.out.iterdir()}
        self.assertEqual(names, {"transfer.npz", "record.json", "w00-trace_inklabels.tif",
                                 "w00-trace_supervision_mask.tif", "w00-trace_inklabels.zarr",
                                 "w00-trace_supervision_mask.zarr"})
        self.assertEqual(self.rec["label_files"], {"inklabels": "w00-trace_inklabels.tif",
                                                   "supervision_mask": "w00-trace_supervision_mask.tif"})
        self.assertEqual(self.rec["villa"]["segment"], "w00-trace")
        self.assertTrue(self.rec["villa"]["trainer_ready_here"])
        rec, a = lx.load(self.out)
        self.assertEqual(int(a["supervision"].sum()), rec["labelled_px"])
        self.assertGreater(rec["labelled_px"], 1000)

    def test_villafmt_labels_find_picks_the_pair(self):
        """villa's discover_segment_labels, as kit.villafmt reimplements it, picks the .zarr pair (the trainer's
        default and only extension) and the TIFF pair; it found nothing in the names written before."""
        from kit import villafmt
        rep = villafmt.find_labels(self.out)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["selected"], {"inklabels": "w00-trace_inklabels.zarr",
                                           "supervision_mask": "w00-trace_supervision_mask.zarr",
                                           "validation_mask": None})
        self.assertEqual({r["layout"] for r in rep["assets"] if r["extension"] == ".zarr"}, {"villa-zyx"})
        self.assertFalse(rep["warnings"])
        tif = villafmt.find_labels(self.out, extension=".tif")
        self.assertEqual(tif["selected"]["supervision_mask"], "w00-trace_supervision_mask.tif")
        legacy = self.root / "legacy" / "w00-trace"
        lx.carry(self.trace, self.pub, self.labels, legacy, voxel_um=VOXEL_UM, names="legacy")
        self.assertFalse(villafmt.find_labels(legacy)["ok"])
        cli_out = io.StringIO()
        with contextlib.redirect_stdout(cli_out):
            self.assertEqual(villafmt.main(["labels", "find", str(self.out)]), 0)

    def test_label_zarr_is_villas_layout(self):
        tif = tifffile.imread(str(self.out / "w00-trace_inklabels.tif"))
        self.assertEqual(tif.shape, (150, 200))
        for kind in ("inklabels", "supervision_mask"):
            path = self.out / f"w00-trace_{kind}.zarr"
            tif = tifffile.imread(str(self.out / f"w00-trace_{kind}.tif"))
            self.assertTrue(tif.any())
            attrs = json.loads((path / ".zattrs").read_text())
            self.assertEqual(json.loads((path / ".zgroup").read_text())["zarr_format"], 2)
            ms = attrs["multiscales"][0]
            self.assertEqual(ms["version"], "0.4")
            self.assertEqual(ms["name"], f"w00-trace_{kind}")
            self.assertEqual([a["name"] for a in ms["axes"]], ["z", "y", "x"])
            self.assertEqual([d["path"] for d in ms["datasets"]], ["0", "1", "2", "3", "4", "5"])
            self.assertEqual(ms["datasets"][1]["coordinateTransformations"],
                             [{"type": "scale", "scale": [1.0, 2.0, 2.0]}])
            g = zarr.open_group(str(path), mode="r")
            want = [(65, 150, 200), (65, 75, 100), (65, 38, 50), (65, 19, 25), (65, 10, 13), (65, 5, 7)]
            self.assertEqual([tuple(g[str(lv)].shape) for lv in range(6)], want)
            for lv in range(6):
                meta = json.loads((path / str(lv) / ".zarray").read_text())
                self.assertEqual(meta["zarr_format"], 2)
                self.assertEqual(meta["chunks"], [65, 128, 128])
                self.assertEqual(meta["dtype"], "|u1")
                self.assertEqual(meta["fill_value"], 0)
                self.assertEqual(meta["dimension_separator"], "/")
                self.assertEqual({k: meta["compressor"][k] for k in ("id", "cname", "clevel", "shuffle")},
                                 {"id": "blosc", "cname": "zstd", "clevel": 3, "shuffle": 2})
                self.assertEqual(json.loads((path / str(lv) / ".zattrs").read_text())["_ARRAY_DIMENSIONS"],
                                 ["z", "y", "x"])
                vol = np.asarray(g[str(lv)][...])
                np.testing.assert_array_equal(vol[32], tif[::2 ** lv, ::2 ** lv])
                self.assertEqual(int(np.delete(vol, 32, axis=0).astype(np.int64).sum()), 0)
                # villa's trainer reads plane shape[0] // 2 of the level it opens (dataset.py:100-105)
                np.testing.assert_array_equal(vol[vol.shape[0] // 2], tif[::2 ** lv, ::2 ** lv])
            self.assertTrue((path / "0" / "0" / "0" / "0").is_file())   # "/" chunk keys

    def test_segment_option_and_refused_names(self):
        out = self.root / "named"
        rec = lx.carry(self.trace, self.pub, self.labels, out, voxel_um=VOXEL_UM, segment="pherc0139-w016",
                       names="villa", label_zarr=False)["record"]
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["pherc0139-w016_inklabels.tif", "pherc0139-w016_supervision_mask.tif", "record.json",
                          "transfer.npz"])
        self.assertIsNone(rec["villa"]["zarr"])
        self.assertTrue(any("create_label_zarrs" in step for step in rec["villa"]["next"]))
        self.assertFalse(rec["villa"]["trainer_ready_here"])
        for bad in ("", "a/b", "..", " w00"):
            with self.assertRaises(lx.VerifyError):
                lx.carry(self.trace, self.pub, self.labels, self.root / "bad", voxel_um=VOXEL_UM, segment=bad,
                         names="villa")
        with self.assertRaises(lx.VerifyError):
            lx.label_files("w00", "kaggle")
        self.assertFalse((self.root / "bad").exists())

    def test_an_empty_label_writes_no_chunks(self):
        path = self.root / "blank_inklabels.zarr"
        layout = lx.write_villa_label_zarr(path, np.zeros((300, 260), np.uint8))
        self.assertEqual(layout["shapes"][0], [65, 300, 260])
        g = zarr.open_group(str(path), mode="r")
        self.assertEqual(int(np.asarray(g["0"][...]).sum()), 0)
        self.assertFalse((path / "0" / "0").exists())
        with self.assertRaises(lx.VerifyError):
            lx.write_villa_label_zarr(path, np.zeros((3, 4, 5), np.uint8))

    def test_command_line(self):
        out = self.root / "cli"
        argv = ["labelxfer", "carry", str(self.trace), "--from", str(self.pub), "--labels", str(self.labels),
                "--out", str(out), "--voxel-um", str(VOXEL_UM), "--segment", "S1"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(argv), 0)
            self.assertEqual(cli.main(argv[:-2] + ["--names", "legacy", "--out", str(self.root / "cli-legacy")]),
                             0)
            self.assertEqual(cli.main(argv[:-2] + ["--segment", "a/b"]), 2)
        self.assertTrue((out / "S1_supervision_mask.zarr" / ".zattrs").is_file())
        self.assertTrue((self.root / "cli-legacy" / "supervision.tif").is_file())


@unittest.skipIf(lx is None, "numpy, scipy, tifffile and zarr are needed for kit labelxfer")
class VillaCompositeNameTest(unittest.TestCase):
    """villa's create_label_zarrs halves a TIFF by mean when its lowercased stem holds "max" or "composite" and starts
    with its folder's name (villa main 8aa507c12, create_label_zarrs.py:67-76, 559-561), so a label named after such a
    segment would turn grey below level 0 if villa converted it; write keeps nearest and says so."""

    def test_a_segment_name_villa_would_take_for_a_composite_is_warned(self):
        h, w = 21, 17
        ink = np.indices((h, w)).sum(0) % 2 == 0      # a checkerboard: nearest keeps 255 at level 1, mean gives grey
        arrays = {"src_row": np.zeros((h, w), np.int32), "src_col": np.zeros((h, w), np.int32),
                  "gap": np.zeros((h, w), np.float32), "offset": np.zeros((h, w), np.float32),
                  "status": np.full((h, w), lx.LABELLED, np.uint8), "ink": ink, "supervision": np.ones((h, w), bool)}
        with tempfile.TemporaryDirectory() as tmp:
            for seg, token in (("maxi-w00", "max"), ("PHerc0332-Composite", "composite"), ("w00-trace", None)):
                out = Path(tmp) / seg
                rec = lx.write(out, arrays, {}, files=lx.label_files(seg))
                warnings = rec["villa"].get("warnings")
                if token is None:
                    self.assertIsNone(warnings)
                    continue
                self.assertEqual(len(warnings), 1)
                self.assertIn(repr(token), warnings[0])
                self.assertIn("create_label_zarrs", warnings[0])
                level1 = np.asarray(zarr.open_group(str(out / f"{seg}_inklabels.zarr"), mode="r")["1"][32])
                np.testing.assert_array_equal(level1, ink.astype(np.uint8)[::2, ::2] * 255)   # nearest, not mean
                self.assertEqual(set(np.unique(level1).tolist()), {255})


@unittest.skipIf(lx is None, "numpy, scipy, tifffile and zarr are needed for kit labelxfer")
class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pub = write_mesh(self.root / "pub.tifxyz", published, 24, 32, 0.1)
        self.ink, self.sup = blob_labels()
        self.labels = write_labels(self.root / "labels", self.ink, self.sup)

        def shifted(r, c):
            x = 57.0 + 5.0 * c
            return x, 40.0 + 5.0 * r, bump(x)
        self.trace = write_mesh(self.root / "trace.tifxyz", shifted, 30, 40, 0.2)
        self.xfer = self.root / "xfer"
        lx.carry(self.trace, self.pub, self.labels, self.xfer, voxel_um=VOXEL_UM)
        rec, a = lx.load(self.xfer)
        rng = np.random.default_rng(5)
        noise = rng.random(a["status"].shape).astype(np.float32)
        self.maps = {"f": self.root / "f.tif", "r": self.root / "r.tif", "s": self.root / "s.tif"}
        tifffile.imwrite(str(self.maps["f"]), (0.6 * a["ink"] + 0.4 * noise).astype(np.float32))
        tifffile.imwrite(str(self.maps["r"]), noise)
        tifffile.imwrite(str(self.maps["s"]), rng.random(noise.shape).astype(np.float32))
        lr, lc = lx.labels_on_canvas(self.ink, self.sup, (240, 320))
        pub_ink = self.ink[np.ix_(lr, lc)]
        self.ref = self.root / "ref.tif"
        tifffile.imwrite(str(self.ref), (0.2 * pub_ink + 0.8 * rng.random(pub_ink.shape)).astype(np.float32))

    def tearDown(self):
        self.tmp.cleanup()

    def test_forward_controls_and_paired_reference(self):
        res = lx.score(self.xfer, self.maps, self.ref, draws=200)
        self.assertEqual(res["forward"]["auc"], 1.0)
        self.assertLess(abs(res["reverse"]["auc"] - 0.5), 0.05)
        self.assertLess(abs(res["shuffled"]["auc"] - 0.5), 0.05)
        self.assertEqual(len(res["displaced"]["directions"]), 4)
        self.assertLess(res["displaced"]["max_auc"], 0.8)
        ref = res["reference"]["on_carried_pixels"]
        self.assertTrue(0.6 < ref["auc"] < 1.0)
        self.assertEqual(ref["ink_px"] + ref["background_px"], res["labelled_px"])
        p = res["paired"]
        self.assertEqual((p["draws"], p["block_px"], p["seed"]), (200, lx.BLOCK_PX, 20261009))
        self.assertGreater(p["difference"], 0)
        self.assertGreater(p["ci95"][0], 0)
        self.assertEqual(p["pixels"], res["labelled_px"])
        # fixed seed: the same interval again
        self.assertEqual(lx.score(self.xfer, self.maps, self.ref, draws=200)["paired"]["ci95"], p["ci95"])

    def test_a_map_of_another_canvas_is_refused(self):
        with self.assertRaises(lx.VerifyError):
            lx.score(self.xfer, {"f": self.ref})
        with self.assertRaises(lx.VerifyError):
            lx.score(self.xfer, self.maps, reference=self.maps["f"])

    def test_command_line(self):
        def run(argv):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(argv)
            return code, json.loads(buf.getvalue())
        code, res = run(["labelxfer", "canvas", str(self.pub), "--json"])
        self.assertEqual((code, res["canvas"]), (0, [240, 320]))
        code, res = run(["labelxfer", "carry", str(self.trace), "--from", str(self.pub), "--labels", str(self.labels),
                         "--out", str(self.root / "cli"), "--voxel-um", str(VOXEL_UM), "--surface-shape", "240", "320"])
        self.assertEqual(code, 0)
        self.assertGreater(res["labelled_px"], 20000)
        code, res = run(["labelxfer", "check", str(self.pub), "--labels", str(self.labels), "--voxel-um",
                         str(VOXEL_UM)])
        self.assertEqual((code, res["passes"]), (0, True))
        code, res = run(["labelxfer", "score", str(self.root / "cli"), str(self.maps["f"]), "--reverse",
                         str(self.maps["r"]), "--reference", str(self.ref), "--draws", "50"])
        self.assertEqual((code, res["forward"]["auc"]), (0, 1.0))
        self.assertIn("paired", res)


def write_render(path, arr):
    """An uncompressed one-level OME-Zarr v2 of a layers x H x W uint8 render, one chunk (as vc_render_tifxyz's
    --zarr-output is read back by kit)."""
    root = Path(path)
    (root / "0" / "0" / "0").mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (root / ".zattrs").write_text(json.dumps({"multiscales": [{
        "version": "0.4", "name": "render", "axes": [{"name": a, "type": "space"} for a in "zyx"],
        "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0, 1.0]}]}]}]}))
    (root / "0" / ".zarray").write_text(json.dumps({
        "zarr_format": 2, "shape": list(arr.shape), "chunks": list(arr.shape), "dtype": "|u1", "compressor": None,
        "fill_value": 0, "filters": None, "order": "C", "dimension_separator": "/"}))
    (root / "0" / "0" / "0" / "0").write_bytes(np.ascontiguousarray(arr, dtype=np.uint8).tobytes())
    return root


@unittest.skipIf(lx is None, "numpy, scipy, tifffile and zarr are needed for kit labelxfer")
class CanvasCheckOverlapTest(unittest.TestCase):
    """canvas_check (the render against the canvas formula) and overlap (a trace on a surface, no labels)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pub = write_mesh(self.root / "pub.tifxyz", published, 24, 32, 0.1)
        self.mask = lx.rendered_mask(lx.read_mesh(self.pub))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_render_of_the_canvas_passes_and_one_off_by_pixels_fails(self):
        arr = np.repeat(self.mask[None], 3, 0).astype(np.uint8) * 120
        arr[:, 100:110, 100:110] = 0                # CT with no data inside the canvas is left out, not a miss
        res = lx.canvas_check(self.pub, write_render(self.root / "good.zarr", arr))
        self.assertTrue(res["passes"], res)
        self.assertEqual((res["agreement"], res["render_shape"]), (1.0, [3, 240, 320]))
        shifted = np.roll(arr, 10, axis=2)          # the same render, 10 columns off the formula's canvas
        res = lx.canvas_check(self.pub, write_render(self.root / "shift.zarr", shifted))
        self.assertFalse(res["passes"])
        self.assertLess(res["agreement"], lx.CANVAS_MIN_AGREEMENT)
        res = lx.canvas_check(self.pub, write_render(self.root / "wide.zarr", np.ones((3, 240, 321), np.uint8)))
        self.assertFalse(res["passes"])
        self.assertIn("not layers by the canvas", res["why"])
        res = lx.canvas_check(self.pub, write_render(self.root / "empty.zarr", np.zeros((3, 240, 320), np.uint8)))
        self.assertEqual((res["passes"], res["why"]), (False, "the render is empty"))

    def test_overlap_is_the_carry_without_labels(self):
        def shifted(r, c):
            x = 57.0 + 5.0 * c
            return x, 40.0 + 5.0 * r, bump(x)
        trace = write_mesh(self.root / "trace.tifxyz", shifted, 30, 40, 0.2)
        res = lx.overlap(trace, self.pub, self.root / "ov", voxel_um=VOXEL_UM)
        carried = lx.carry(trace, self.pub, None, voxel_um=VOXEL_UM)["record"]
        self.assertEqual(res["labels"], "never read")
        self.assertEqual(res["overlap_px"], carried["pixels"]["carried_unsupervised"])
        self.assertGreater(res["overlap_px"], 20000)
        self.assertEqual(res["overlap_cm2"], carried["carried_cm2"])
        mask = tifffile.imread(str(self.root / "ov" / "mask.tif"))
        self.assertEqual(int((mask > 0).sum()), res["overlap_px"])
        self.assertEqual(json.loads((self.root / "ov" / "record.json").read_text())["overlap_px"], res["overlap_px"])

        def next_winding(r, c):
            x = 20.0 + 10.0 * c
            return x, 20.0 + 10.0 * r, bump(x) + 12.0
        far = write_mesh(self.root / "far.tifxyz", next_winding, 24, 32, 0.1)
        self.assertEqual(lx.overlap(far, self.pub, voxel_um=VOXEL_UM)["overlap_px"], 0)

    def test_coverage_numbers(self):
        ink, sup = blob_labels()
        labels = write_labels(self.root / "labels", ink, sup)
        rec = lx.carry(self.pub, self.pub, labels, voxel_um=VOXEL_UM)["record"]
        cov = lx.coverage(rec)
        self.assertEqual(cov["share_of_published_supervision_reached"], 1.0)
        self.assertEqual(cov["gap_vox_median"], 0.0)
        self.assertLessEqual(cov["abs_offset_labelled_vox"]["percentiles"]["95"], 0.01)
        self.assertEqual(cov["abs_offset_labelled_vox"]["share_within"]["1"], 1.0)
        self.assertEqual(cov["carried_share_of_rendered"], round(rec["carried_cm2"] / rec["rendered_cm2"], 4))
        self.assertEqual(cov["labelled_cm2"], rec["labelled_cm2"])


@unittest.skipIf(lx is None, "numpy, scipy, tifffile and zarr are needed for kit labelxfer")
class ReportSurfaceTest(unittest.TestCase):
    """0841-ag405, the ink bar's report surface: its labels are refused unless report is set."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pub = write_mesh(self.root / "pub.tifxyz", published, 24, 32, 0.1)
        ink, sup = blob_labels()
        self.ag405 = write_labels(self.root / "labels" / "0841-ag405", ink, sup)
        self.w00 = write_labels(self.root / "labels" / "0841-w00", ink, sup)

    def tearDown(self):
        self.tmp.cleanup()

    def test_carry_check_and_score_refuse_report_labels(self):
        with self.assertRaises(lx.VerifyError) as cm:
            lx.carry(self.pub, self.pub, self.ag405, voxel_um=VOXEL_UM)
        self.assertIn("report surface", str(cm.exception))
        with self.assertRaises(lx.VerifyError):
            lx.check(self.pub, self.ag405, voxel_um=VOXEL_UM)
        out = self.root / "x"
        lx.carry(self.pub, self.pub, self.ag405, out, voxel_um=VOXEL_UM, report=True)
        tifffile.imwrite(str(self.root / "f.tif"), np.zeros((240, 320), np.float32))
        with self.assertRaises(lx.VerifyError):
            lx.score(out, {"f": self.root / "f.tif"})
        self.assertIn("forward", lx.score(out, {"f": self.root / "f.tif"}, report=True))
        lx.carry(self.pub, self.pub, self.w00, voxel_um=VOXEL_UM)      # any other labels go through

    def test_command_line_refuses_them_without_report(self):
        argv = ["labelxfer", "carry", str(self.pub), "--from", str(self.pub), "--labels", str(self.ag405), "--out",
                str(self.root / "cli"), "--voxel-um", str(VOXEL_UM)]
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(argv), 2)
            self.assertEqual(cli.main(["labelxfer", "check", str(self.pub), "--labels", str(self.ag405),
                                       "--voxel-um", str(VOXEL_UM)]), 2)
            self.assertEqual(cli.main(argv + ["--report"]), 0)
        self.assertIn("report surface", err.getvalue())


class ReportNameTest(unittest.TestCase):
    """Which paths name a report surface's labels: standard library."""

    def test_names(self):
        from kit import labelxfer
        for path in ("work/autopipe/run/labels/0841-ag405", "x/ag405/inklabels",
                     "PHerc0841/segments/20260221022814-auto_grown_20260220174252405/ink-labels/2.403um-volume-"
                     "20260319124803/20260918"):
            self.assertEqual(labelxfer.report_surface(path), "0841-ag405", path)
        for path in ("work/autopipe/run/labels/0841-w00", "labels/0841-ag896", "work/ag4050/labels"):
            self.assertIsNone(labelxfer.report_surface(path), path)
        with self.assertRaises(labelxfer.VerifyError):
            labelxfer.guard_labels("labels/0841-ag405")
        self.assertEqual(labelxfer.guard_labels("labels/0841-ag405", report=True), "0841-ag405")
        self.assertIsNone(labelxfer.guard_labels(None))


def _vc3d_render_tool():
    try:
        from kit import vc3d
        tools = vc3d.find_tools()
    except Exception:  # noqa: BLE001 - no VC3D here
        return None
    return tools if tools and tools.has("vc_render_tifxyz") else None


@unittest.skipIf(lx is None or _vc3d_render_tool() is None,
                 "needs numpy, scipy, tifffile, zarr and a VC3D build with vc_render_tifxyz (VC_BIN)")
class Vc3dCanvasTest(unittest.TestCase):
    """The canvas formula against villa's own vc_render_tifxyz: a volume whose value is 2x (or 2y) rendered along
    a curved tifxyz with a hole gives back, at each rendered pixel, the x (or y) sample_pixels says it samples, to
    the uint8 quantization, and renders exactly rendered_mask; canvas_check passes on its zarr render."""

    def test_sampled_positions_and_mask_match_the_renderer(self):
        import subprocess
        from kit import vc3d
        tools = _vc3d_render_tool()
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            n = 128
            vols = {"x": vc3d.write_zarr_u8(work / "vx.zarr", [n] * 3, 64, lambda v: min(255, 2 * v), axis="x"),
                    "y": vc3d.write_zarr_u8(work / "vy.zarr", [n] * 3, 64, lambda v: min(255, 2 * v), axis="y")}

            def curved(r, c):
                return (4 + 19.0 * c + 2.0 * np.sin(r), 4 + 19.0 * r + 2.0 * np.cos(c),
                        64 + 5 * np.sin(c / 2.0) + 3 * np.cos(r / 3.0))
            mesh = write_mesh(work / "m.tifxyz", curved, 7, 6, 0.07, holes=[(3, 2)])
            meta = json.loads((mesh / "meta.json").read_text())
            (mesh / "meta.json").write_text(json.dumps(dict(meta, uuid="m")))     # VC3D loads a tifxyz by its uuid
            M = lx.read_mesh(mesh)
            h, w = lx.canvas_shape(M)
            R, C = np.mgrid[0:h, 0:w]
            pts, _, ok = lx.sample_pixels(M, R, C)
            for k, ax in enumerate("xy"):
                out = work / f"r-{ax}.zarr"
                argv = tools.argv("vc_render_tifxyz", "--volume", vols[ax], "--segmentation", mesh, "--scale", "1",
                                  "--group-idx", "0", "--num-slices", "1", "--cache-gb", "1", "--zarr-output", out)
                p = subprocess.run(argv, capture_output=True, text=True, timeout=300)
                self.assertEqual(p.returncode, 0, p.stdout[-2000:] + p.stderr[-2000:])
                from kit.vc3d_region import Volume
                img = np.asarray(Volume(str(out)).read(0, [[0, 1], [0, h], [0, w]]))[0]
                self.assertEqual(img.shape, (h, w))
                self.assertEqual(int(((img > 0) != ok).sum()), 0)
                err = np.abs(img[ok].astype(float) / 2.0 - pts[..., k][ok])
                self.assertLessEqual(float(err.max()), 0.51)
                self.assertTrue(lx.canvas_check(mesh, out)["passes"])


def good_scores():
    """A scores.json as AutoPipeline writes it with score.transfer and three traces from each seed: t00-r0 rejected
    by qa, t00-r1 the primary with every number on the passing side, t00-r2 accepted later with failing numbers
    (never read), and seed 1's traces."""
    def scored(f, r, sh, dmax, ci):
        return {"seed_index": 0, "accepted": True, "canvas_check": {"passes": True, "agreement": 1.0},
                "report_overlap": {"0841-ag405": {"overlap_cm2": 0.02}},
                "segments": {"0841-w00": {
                    "scorable": True,
                    "coverage": {"labelled_cm2": 0.9, "ink_px": 20000, "background_px": 80000, "carried_cm2": 1.1,
                                 "rendered_cm2": 2.0, "carried_share_of_rendered": 0.55,
                                 "share_of_published_supervision_reached": 0.4, "gap_vox_median": 1.2,
                                 "gap_share_within_4_vox": 0.6, "share_refused_by_normal_test": 0.01,
                                 "abs_offset_labelled_vox": {"labelled_px": 100000,
                                                             "percentiles": {"50": 0.9, "95": 3.1}}},
                    "models": {"ink_9um-seed42": {
                        "forward": {"auc": f}, "reverse": {"auc": r}, "shuffled": {"auc": sh},
                        "displaced": {"max_auc": dmax}, "reference": {"on_carried_pixels": {"auc": 0.75}},
                        "paired": {"difference": -0.01, "ci95": ci}}}}}}
    planned = [f"t0{i}-r{k}" for i in range(2) for k in range(3)]
    surfaces = {"t00-r0": {"seed_index": 0, "repeat": 0, "accepted": False, "scorable": False,
                           "why": "rejected by qa: partly seated",
                           "failure": {"stage": "qa", "kind": "ours", "reason": "rejected by qa: partly seated"}},
                "t00-r1": dict(scored(0.74, 0.51, 0.55, 0.6, [-0.025, 0.004]), repeat=1),
                "t00-r2": dict(scored(0.60, 0.70, 0.60, 0.6, [-0.2, -0.1]), repeat=2)}
    for k in range(3):
        surfaces[f"t01-r{k}"] = {"seed_index": 1, "repeat": k, "accepted": False, "scorable": False, "why": "qa",
                                 "failure": {"stage": "qa", "kind": "ours", "reason": "rejected by qa"}}
    return {
        "plan": "0" * 64,
        "checks": {"0841-w00": {"passes": True}},
        "references": {"0841-w00": {"models": {"ink_9um-seed42": {
            "whole": {"forward": {"auc": 0.7481}, "control": {"auc": 0.5012}}}}}},
        "traces": {"planned": planned, "repeats": 3, "seeds": {s: int(s[2]) for s in planned}},
        "surfaces": surfaces}


def run_state(**edits):
    """A state.json of arm A that stopped after render: the readout then has no scores."""
    planned = [{"sid": f"t0{i}-r{k}", "seed_index": i, "repeat": k, "seed": [1, 2, 3]} for i in range(2) for k in range(3)]
    surfaces = {s["sid"]: {"surface": f"traces/{s['sid']}", "seed_index": s["seed_index"], "repeat": s["repeat"],
                           "qa": {"accepted": False, "reasons": ["partly seated"], "failure": {"kind": "ours"}},
                           "accepted": False} for s in planned}
    surfaces["t00-r1"].update(accepted=True, qa={"accepted": True, "reasons": []}, render={"zarr": "r.zarr"})
    st = {"stages": {k: {"status": "done"} for k in ("acquire", "axis", "seeds", "trace", "qa", "flatten", "audit",
                                                    "render")},
          "planned_traces": planned, "trace_failures": {}, "surfaces": surfaces}
    st.update(edits)
    return st


class ReadoutTest(unittest.TestCase):
    """The preregistered readout (a note of the source repository, amended 10 Oct 2026) from a
    scores.json or a state.json: standard library."""

    def setUp(self):
        from kit import labelxfer
        self.lx = labelxfer

    def verdict(self, edit=None):
        sc = good_scores()
        if edit:
            edit(sc)
        return self.lx.readout(sc)

    def model(self, sc, sid="t00-r1"):
        return sc["surfaces"][sid]["segments"]["0841-w00"]["models"]["ink_9um-seed42"]

    def reject(self, sc, sid, kind="ours", stage="qa"):
        sc["surfaces"][sid] = {"seed_index": int(sid[2]), "repeat": int(sid[-1]), "accepted": False if stage == "qa"
                               else None, "scorable": False, "why": "x",
                               "failure": {"stage": stage, "kind": kind, "reason": f"{stage} {kind}"}}

    def test_pass_on_the_first_accepted_repeat_with_coverage_beside_it(self):
        res = self.verdict()
        self.assertEqual((res["verdict"], res["reasons"]), ("PASS", []))
        n = res["numbers"]
        self.assertEqual((n["surface"], n["passed_over"]), ("t00-r1", ["t00-r0"]))
        self.assertEqual([c["surface"] for c in n["candidates"]], ["t00-r0", "t00-r1", "t00-r2"])
        self.assertEqual(n["difference_ci95"], [-0.025, 0.004])
        cov = n["coverage"]
        for k in ("share_of_published_supervision_reached", "carried_cm2", "rendered_cm2", "carried_share_of_rendered",
                  "gap_vox_median", "abs_offset_labelled_vox", "share_refused_by_normal_test"):
            self.assertIsNotNone(cov[k], k)
        self.assertEqual(cov["report_overlap_cm2"], {"0841-ag405": 0.02})
        self.assertIn("says nothing about whether the trace stays on the winding", res["interpretation"])

    def test_launch_order_decides_not_the_numbers(self):
        # t00-r0 accepted: it is the primary, though t00-r1 scores better on the same rule
        def accept_r0(sc):
            sc["surfaces"]["t00-r0"] = dict(sc["surfaces"]["t00-r2"], repeat=0)
        res = self.verdict(accept_r0)
        self.assertEqual((res["numbers"]["surface"], res["verdict"]), ("t00-r0", "FAIL"))
        # the order is traces.planned, not the order of the surfaces record
        def shuffled(sc):
            sc["surfaces"] = dict(reversed(list(sc["surfaces"].items())))
        self.assertEqual(self.verdict(shuffled)["numbers"]["surface"], "t00-r1")
        # a named surface is read by the same rule, never instead of the primary
        res = self.lx.readout(good_scores(), surface="t00-r2")
        self.assertEqual((res["numbers"]["surface"], res["verdict"]), ("t00-r2", "FAIL"))

    def test_each_control_on_our_trace_can_fail_it(self):
        cases = [(lambda sc: self.model(sc)["reverse"].update(auc=0.56), "reverse control"),
                 (lambda sc: self.model(sc)["shuffled"].update(auc=0.70), "shuffled control"),
                 (lambda sc: self.model(sc)["displaced"].update(max_auc=0.695), "displaced control"),
                 (lambda sc: self.model(sc)["paired"].update(ci95=[-0.031, 0.0]), "not non-inferior")]
        for edit, why in cases:
            res = self.verdict(edit)
            self.assertEqual(res["verdict"], "FAIL", why)
            self.assertEqual(len(res["reasons"]), 1)
            self.assertIn(why, res["reasons"][0])
        # at the edges the rule still passes
        res = self.verdict(lambda sc: (self.model(sc)["reverse"].update(auc=0.55),
                                       self.model(sc)["paired"].update(ci95=[-0.03, 0.0])))
        self.assertEqual(res["verdict"], "PASS")

    def test_no_accepted_repeat_is_fail_when_our_chain_decided_every_one(self):
        def none_accepted(sc):
            self.reject(sc, "t00-r1")
            self.reject(sc, "t00-r2", stage="trace")        # the tracer exited, or the seed check refused it
        res = self.verdict(none_accepted)
        self.assertEqual(res["verdict"], "FAIL")
        self.assertIn("none of seed 0's 3 traces was accepted by qa", res["reasons"][0])
        # one that stopped for the infrastructure leaves the primary undecided: VOID
        res = self.verdict(lambda sc: (none_accepted(sc), self.reject(sc, "t00-r2", "infrastructure", "trace")))
        self.assertEqual(res["verdict"], "VOID")
        self.assertIn("t00-r2", res["reasons"][0])
        # a planned trace with no record at all is the infrastructure's too
        res = self.verdict(lambda sc: (none_accepted(sc), sc["surfaces"].pop("t00-r0")))
        self.assertEqual(res["verdict"], "VOID")

    def test_the_primary_stopped_before_a_map_by_who_stopped_it(self):
        def render(kind):
            def edit(sc):
                sc["surfaces"]["t00-r1"] = {"seed_index": 0, "repeat": 1, "accepted": True, "scorable": False,
                                            "why": "not rendered", "failure": {"stage": "render", "kind": kind,
                                                                               "reason": "not rendered"}}
            return edit
        self.assertEqual(self.verdict(render("ours"))["verdict"], "FAIL")
        self.assertEqual(self.verdict(render("infrastructure"))["verdict"], "VOID")
        # never the next accepted repeat instead
        self.assertEqual(self.verdict(render("ours"))["numbers"]["surface"], "t00-r1")

    def test_carried_labels_too_small_fail_and_not_carried_void(self):
        def small(sc):
            sc["surfaces"]["t00-r1"]["segments"]["0841-w00"] = {
                "scorable": False, "why": "0.1 cm2 of carried labels",
                "failure": {"stage": "transfer", "kind": "ours", "reason": "0.1 cm2"}}
        self.assertEqual(self.verdict(small)["verdict"], "FAIL")

        def canvas(sc):
            sc["surfaces"]["t00-r1"]["segments"]["0841-w00"] = {
                "scorable": False, "why": "labels not carried: canvas check failed: agreement 0.97 under 0.999",
                "failure": {"stage": "transfer", "kind": "infrastructure", "reason": "labels not carried"}}
        self.assertEqual(self.verdict(canvas)["verdict"], "VOID")

    def test_the_published_side_and_missing_pieces_void_it(self):
        cases = [lambda sc: sc["checks"]["0841-w00"].update(passes=False),
                 lambda sc: sc.pop("checks"),
                 lambda sc: sc["references"]["0841-w00"]["models"]["ink_9um-seed42"]["whole"]["forward"].update(
                     auc=0.7420),
                 lambda sc: sc["references"]["0841-w00"]["models"]["ink_9um-seed42"]["whole"]["control"].update(
                     auc=0.58),
                 lambda sc: self.model(sc).pop("shuffled"),
                 lambda sc: sc["surfaces"]["t00-r1"]["segments"].pop("0841-w00"),
                 lambda sc: sc["traces"].update(repeats=1)]
        for k, edit in enumerate(cases):
            self.assertEqual(self.verdict(edit)["verdict"], "VOID", k)
        # VOID wins over FAIL, and every reason is listed
        res = self.verdict(lambda sc: (sc["checks"]["0841-w00"].update(passes=False),
                                       self.model(sc)["reverse"].update(auc=0.9)))
        self.assertEqual(res["verdict"], "VOID")
        self.assertEqual(len(res["reasons"]), 2)

    def test_from_the_state_alone(self):
        res = self.lx.readout(None, state=run_state())
        self.assertEqual((res["verdict"], res["numbers"]["surface"]), ("VOID", "t00-r1"))
        self.assertIn("no scores", res["reasons"][0])
        # no t00 accepted, every one by qa: FAIL without any map
        st = run_state()
        st["surfaces"]["t00-r1"].update(accepted=False, qa={"accepted": False, "reasons": ["self-intersections"],
                                                            "failure": {"kind": "ours"}})
        self.assertEqual(self.lx.readout(None, state=st)["verdict"], "FAIL")
        # one t00 never traced: the seed check refused it (ours) or the tool could not run (infrastructure)
        for kind, want in (("ours", "FAIL"), ("infrastructure", "VOID")):
            s2 = json.loads(json.dumps(st))
            s2["surfaces"].pop("t00-r2")
            s2["trace_failures"]["t00-r2"] = {"kind": kind, "reason": "x"}
            self.assertEqual(self.lx.readout(None, state=s2)["verdict"], want, kind)
        # the primary's render refused by our chain, or cut off with its stage
        s3 = run_state()
        s3["surfaces"]["t00-r1"]["render"] = {"refused": "chunk audit: 9 % missing"}
        self.assertEqual(self.lx.readout(None, state=s3)["verdict"], "FAIL")
        s3["surfaces"]["t00-r1"]["render"] = {}
        s3["stages"]["render"] = {"status": "failed", "kind": "infrastructure"}
        self.assertEqual(self.lx.readout(None, state=s3)["verdict"], "VOID")
        # no trace planned: the stage that stopped it says who decided
        for kind, want in (("ours", "FAIL"), ("infrastructure", "VOID")):
            s4 = run_state(planned_traces=[], surfaces={})
            s4["stages"] = {"acquire": {"status": "done"}, "seeds": {"status": "failed", "kind": kind, "error": "e"}}
            s4.pop("planned_traces")
            self.assertEqual(self.lx.readout(None, state=s4)["verdict"], want, kind)

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "scores.json"
            f.write_text(json.dumps(good_scores()))
            s = Path(d) / "state.json"
            s.write_text(json.dumps(run_state()))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.main(["labelxfer", "readout", str(f)])
            self.assertEqual((code, json.loads(buf.getvalue())["verdict"]), (0, "PASS"))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.main(["labelxfer", "readout", str(Path(d) / "none.json"), "--state", str(s)])
            self.assertEqual((code, json.loads(buf.getvalue())["verdict"]), (0, "VOID"))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["labelxfer", "readout", str(Path(d) / "none.json")]), 2)
                self.assertEqual(cli.main(["labelxfer", "readout"]), 2)


if __name__ == "__main__":
    unittest.main()
