"""Tests for the ink offset diagnostic (scripts/offsetdiag/), on synthetic data only: no network, no scan, no model."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TOOL = ROOT / "scripts" / "offsetdiag"
sys.path.insert(0, str(TOOL))

try:
    import numpy as np
except ImportError:          # the map tools' dependencies are optional for the repository's tests
    np = None
try:
    import scipy  # noqa: F401
except ImportError:
    scipy = None
try:
    import zarr  # noqa: F401
except ImportError:
    zarr = None

NEEDS = np is None or scipy is None


def write_zarr2(folder, arr, chunks):
    """A minimal uncompressed zarr v2 array on disk, chunk files named z/y/x, edge chunks stored whole."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".zarray").write_text(json.dumps({
        "zarr_format": 2, "shape": list(arr.shape), "chunks": list(chunks), "dtype": "|u1", "compressor": None,
        "fill_value": 0, "order": "C", "filters": None, "dimension_separator": "/"}))
    grid = [range(-(-s // c)) for s, c in zip(arr.shape, chunks)]
    for cz in grid[0]:
        for cy in grid[1]:
            for cx in grid[2]:
                block = np.zeros(chunks, np.uint8)
                part = arr[cz * chunks[0]:(cz + 1) * chunks[0], cy * chunks[1]:(cy + 1) * chunks[1],
                           cx * chunks[2]:(cx + 1) * chunks[2]]
                block[:part.shape[0], :part.shape[1], :part.shape[2]] = part
                p = folder / str(cz) / str(cy) / str(cx)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(block.tobytes())
    return str(folder)


def ramp_volume(shape=(64, 64, 64)):
    """uint8 volume whose value is 2 * z."""
    z = np.arange(shape[0], dtype=np.int64)[:, None, None]
    return np.broadcast_to(2 * z, shape).astype(np.uint8).copy()


def flat_mesh(h=24, w=24, z=30.0):
    """A flat mesh at height z on a unit grid: x = col + 10, y = row + 10 (scale 1)."""
    rr, cc = np.meshgrid(np.arange(h, dtype=np.float64), np.arange(w, dtype=np.float64), indexing="ij")
    xyz = np.stack([cc + 10, rr + 10, np.full_like(rr, z)])
    return xyz, np.ones((h, w), bool), 1.0


@unittest.skipIf(NEEDS, "needs numpy and scipy")
class ReaderTest(unittest.TestCase):
    def test_read_box_crosses_chunks_and_fills_outside(self):
        import oddata as D
        with tempfile.TemporaryDirectory() as t:
            arr = (np.arange(20 * 18 * 22) % 251).astype(np.uint8).reshape(20, 18, 22)
            z = D.Zarr2(write_zarr2(Path(t) / "a", arr, (8, 8, 8)), cache=Path(t) / "cache")
            self.assertEqual(z.shape, (20, 18, 22))
            np.testing.assert_array_equal(z.read_box((3, 5, 7), (17, 16, 21)), arr[3:17, 5:16, 7:21])
            box = z.read_box((-2, 0, 0), (2, 2, 2))
            np.testing.assert_array_equal(box[:2], 0)
            np.testing.assert_array_equal(box[2:], arr[:2, :2, :2])
            self.assertTrue(any((Path(t) / "cache").rglob("*")))     # chunks cached on disk

    def test_missing_chunk_reads_as_fill(self):
        import oddata as D
        with tempfile.TemporaryDirectory() as t:
            folder = write_zarr2(Path(t) / "a", np.full((16, 16, 16), 7, np.uint8), (8, 8, 8))
            os.remove(Path(folder) / "1" / "1" / "1")
            z = D.Zarr2(folder)
            self.assertEqual(int(z.read_box((8, 8, 8), (16, 16, 16)).max()), 0)
            self.assertEqual(int(z.read_box((0, 0, 0), (8, 8, 8)).min()), 7)

    def test_sample_is_trilinear(self):
        import oddata as D
        with tempfile.TemporaryDirectory() as t:
            z = D.Zarr2(write_zarr2(Path(t) / "a", ramp_volume((32, 16, 16)), (8, 8, 8)))
            v = z.sample(np.array([[10.5, 20.5, -3.0], [4.0, 4.5, 4.0], [5.0, 5.0, 5.0]]))
            self.assertAlmostEqual(float(v[0]), 21.0, places=4)
            self.assertAlmostEqual(float(v[1]), 41.0, places=4)
            self.assertEqual(float(v[2]), 0.0)                       # outside the array

    def test_refuses_a_missing_array_and_a_wrong_dtype(self):
        import oddata as D
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(D.DataError):
                D.Zarr2(str(Path(t) / "nothing"))
            folder = Path(write_zarr2(Path(t) / "a", np.zeros((8, 8, 8), np.uint8), (8, 8, 8)))
            meta = json.loads((folder / ".zarray").read_text())
            meta["dtype"] = "<u2"
            (folder / ".zarray").write_text(json.dumps(meta))
            with self.assertRaises(D.DataError):
                D.Zarr2(str(folder))

    def test_segment_table(self):
        import oddata as D
        self.assertEqual(set(D.SEGMENTS), {"0841-w00", "0841-ag896"})
        seg = D.segment("0841-w00")
        self.assertEqual(seg["layers"], 28)
        self.assertTrue(seg["scan"].startswith(D.OPEN_DATA))
        with self.assertRaises(D.DataError):
            D.segment("nope")
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "s.json"
            f.write_text(json.dumps({"mine": {"segment": "S", "mesh": "m", "shape": [10, 10], "box": [0, 5, 0, 5],
                                              "normal_sign": 1}}))
            self.assertEqual(D.segment("mine", f)["normal_sign"], 1)
            f.write_text(json.dumps({"bad": {"segment": "S"}}))
            with self.assertRaises(D.DataError):
                D.segments(f)


@unittest.skipIf(NEEDS, "needs numpy and scipy")
class ShiftTest(unittest.TestCase):
    """The render's sign and offset convention: offset o samples the scan at pos + o * n_pub."""

    def setUp(self):
        import oddata as D
        self.tmp = tempfile.TemporaryDirectory()
        self.scan = D.Zarr2(write_zarr2(Path(self.tmp.name) / "scan", ramp_volume(), (16, 16, 16)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_points_down_with_the_published_sign(self):
        import odgeom as G
        xyz, valid, scale = flat_mesh()
        pos, nor, ok = G.surface_grid(xyz, valid, (2, 10), (2, 10), scale, normal_sign=-1)
        self.assertTrue(ok.all())
        np.testing.assert_allclose(nor[:, ok], np.array([[0], [0], [-1]]) * np.ones((1, ok.sum())), atol=1e-9)
        np.testing.assert_allclose(pos[2], 30.0)

    def test_offsets_move_along_n_pub(self):
        import odgeom as G
        offs = [-4.0, 0.0, 2.5]
        img = G.render(flat_mesh(), self.scan, offs, (4, 12), (4, 12), normal_sign=-1, tile=5)
        for k, o in enumerate(offs):                 # value 2 z at z = 30 - o
            np.testing.assert_allclose(img[k], 2 * (30 - o), atol=1e-4)
        flipped = G.render(flat_mesh(), self.scan, offs, (4, 12), (4, 12), normal_sign=1)
        np.testing.assert_allclose(flipped[0], 2 * (30 - 4), atol=1e-4)

    def test_per_pixel_shift_adds_to_the_offset(self):
        import odgeom as G
        shift = np.zeros((6, 6))
        shift[:, 3:] = 3.0
        img = G.render(flat_mesh(), self.scan, [0.0], (4, 10), (4, 10), normal_sign=-1, shift=shift)
        np.testing.assert_allclose(img[0][:, :3], 60.0, atol=1e-4)
        np.testing.assert_allclose(img[0][:, 3:], 54.0, atol=1e-4)

    def test_invalid_mesh_pixels_render_zero(self):
        import odgeom as G
        xyz, valid, scale = flat_mesh()
        valid[:, 12:] = False
        xyz[:, :, 12:] = -1
        img = G.render((xyz, valid, scale), self.scan, [0.0], (0, 24), (0, 24), normal_sign=-1)
        self.assertTrue((img[0][:, 13:] == 0).all())
        self.assertTrue((img[0][:, :11] > 0).all())

    def test_stack_offsets(self):
        import odgeom as G
        o = G.stack_offsets(28)
        self.assertEqual((len(o), o[0], o[-1]), (28, -13.5, 13.5))
        w = G.stack_offsets(28, 8)
        self.assertEqual((len(w), w[0], w[-1]), (44, -21.5, 21.5))


@unittest.skipIf(NEEDS, "needs numpy and scipy")
class ValidateTest(unittest.TestCase):
    def stacks(self, sign):
        rng = np.random.default_rng(0)
        depth = rng.normal(size=(60, 20, 20))            # independent texture per depth step
        offs = np.arange(-18, 18.01, 0.5)
        rendered = np.stack([depth[int(round(2 * o)) + 30] if abs(o) <= 14.5 else rng.normal(size=(20, 20))
                             for o in offs])
        pub = np.stack([depth[int(round(2 * sign * (j - 13.5))) + 30] for j in range(28)])
        return pub, rendered, offs

    def test_matching_convention_passes(self):
        import odgeom as G
        pub, rendered, offs = self.stacks(1)
        best = G.match_layers(pub, rendered, offs, np.ones((20, 20), bool))
        self.assertEqual([o for _, o, _ in best], [j - 13.5 for j in range(28)])
        self.assertTrue(G.check_layers(best))

    def test_flipped_normal_fails(self):
        import odgeom as G
        pub, rendered, offs = self.stacks(-1)
        self.assertFalse(G.check_layers(G.match_layers(pub, rendered, offs, np.ones((20, 20), bool))))


@unittest.skipIf(NEEDS, "needs numpy and scipy")
class LasagnaTest(unittest.TestCase):
    def test_nearest_peak_picks_the_closest_maximum_and_refines(self):
        import odgeom as G
        ts = np.arange(-12, 12.01, 0.25)
        prof = np.stack([200 * np.exp(-0.5 * ((ts - 3.1) / 0.8) ** 2) + 200 * np.exp(-0.5 * ((ts + 6) / 0.8) ** 2),
                         200 * np.exp(-0.5 * ((ts + 1.6) / 0.8) ** 2),
                         100 * np.exp(-0.5 * (ts / 0.8) ** 2),           # below the 160 floor
                         200 * np.exp(-0.5 * ((ts - 10) / 0.8) ** 2)],    # beyond 8 voxels
                        axis=1)
        d = G.nearest_peak(prof, ts)
        self.assertAlmostEqual(float(d[0]), 3.1, delta=0.05)
        self.assertAlmostEqual(float(d[1]), -1.6, delta=0.05)
        self.assertTrue(np.isnan(d[2]) and np.isnan(d[3]))

    def test_cos_profiles_find_a_sheet_above_the_mesh(self):
        import oddata as D
        import odgeom as G
        z = np.arange(64)[:, None, None]
        cos = np.broadcast_to(np.clip(250 * np.exp(-0.5 * ((z - 27.0) / 1.5) ** 2), 0, 255), (64, 64, 64))
        with tempfile.TemporaryDirectory() as t:
            field = D.Zarr2(write_zarr2(Path(t) / "cos", cos.astype(np.uint8), (16, 16, 16)))
            ts = np.arange(-12, 12.01, 0.25)
            prof, ok = G.cos_profiles(flat_mesh(), field, (0, 24), (0, 24), ts, normal_sign=-1, cos_scale=1.0,
                                      stride=8)
            self.assertEqual(ok.shape, (3, 3))
            d = G.nearest_peak(prof, ts)
            np.testing.assert_allclose(d[ok], 3.0, atol=0.1)  # z 27 = 30 - 3: plus 3 along n_pub (down)
            prof2, _ = G.cos_profiles(flat_mesh(), field, (0, 24), (0, 24), ts, normal_sign=-1, cos_scale=0.5,
                                      stride=8)
            self.assertFalse(np.allclose(prof2, prof))           # the field's voxel scale is applied


@unittest.skipIf(NEEDS, "needs numpy and scipy")
class ArmsTest(unittest.TestCase):
    def big(self, h=6, w=5):
        return np.broadcast_to(np.arange(44, dtype=np.uint8)[:, None, None], (44, h, w)).copy()

    def test_take_cuts_28_layers_at_the_shift(self):
        import odarms
        big = self.big()
        for s in (-8, -4, 0, 4, 8):
            a = odarms.take(big, np.full((6, 5), s))
            self.assertEqual(a.shape, (28, 6, 5))
            np.testing.assert_array_equal(a[:, 0, 0], np.arange(28) + 8 + s)
        r = np.zeros((6, 5), np.int64)
        r[2, 3] = -5
        self.assertEqual(int(odarms.take(big, r)[0, 2, 3]), 3)
        with self.assertRaises(ValueError):
            odarms.take(big, np.full((6, 5), 9))
        with self.assertRaises(ValueError):
            odarms.take(big[:40], np.zeros((6, 5), np.int64))

    def test_r0_is_the_render_at_the_published_offsets(self):
        import odarms
        import odgeom as G
        wide = G.stack_offsets(28, odarms.MAX_SHIFT)
        big = np.broadcast_to(wide[:, None, None], (44, 3, 3))
        np.testing.assert_array_equal(odarms.take(big, np.zeros((3, 3), np.int64))[:, 0, 0], G.stack_offsets(28))
        np.testing.assert_array_equal(odarms.take(big, np.full((3, 3), -4))[:, 0, 0], G.stack_offsets(28) - 4)

    def test_arm_controls_match_snap_in_size(self):
        import odarms
        rng = np.random.default_rng(1)
        field = rng.normal(0, 4, size=(10, 12))
        field[0, 0] = 30.0
        valid = np.ones((10, 12), bool)
        valid[9, 11] = False
        arms = odarms.arm_shifts(field, valid)
        self.assertEqual(tuple(arms), odarms.ARMS)
        snap = arms["SNAP"]
        self.assertEqual(int(snap[0, 0]), 8)                        # clipped to MAX_SHIFT
        self.assertEqual(int(snap[9, 11]), 0)                       # invalid pixels stay put
        np.testing.assert_array_equal(arms["ANTI"], -snap)
        rand = arms["RAND"]
        self.assertEqual(int(rand[9, 11]), 0)
        np.testing.assert_array_equal(rand[:9, :11], snap[::-1, ::-1][:9, :11])
        for s in (-8, -4, 0, 4, 8):
            self.assertTrue((arms[odarms.arm_name(s)] == s).all())

    def test_shift_field_smooths_ignores_gaps_and_upsamples(self):
        import odarms
        d = np.full((4, 5), 2.0)
        d[1, 2] = np.nan
        ok = np.ones((4, 5), bool)
        field, stats = odarms.shift_field(d, ok, (32, 40))
        self.assertEqual(field.shape, (32, 40))
        np.testing.assert_allclose(field, 2.0, atol=1e-9)
        self.assertAlmostEqual(stats["coverage"], 19 / 20)
        self.assertAlmostEqual(stats["median"], 2.0)
        none, _ = odarms.shift_field(np.full((4, 5), np.nan), ok, (8, 8))
        self.assertTrue((none == 0).all())

    def test_shift_summary_and_layer_corr(self):
        import odarms
        valid = np.ones((4, 4), bool)
        s = odarms.shift_summary(np.full((4, 4), -4), valid)
        self.assertEqual((s["shift_mean"], s["shift_abs_mean"]), (-4.0, 4.0))
        a = np.random.default_rng(2).normal(size=(3, 4, 4))
        self.assertEqual(odarms.layer_corr(a, 2 * a + 1, valid), {"min": 1.0, "median": 1.0})

    @unittest.skipIf(zarr is None, "needs zarr")
    def test_zarr_round_trip(self):
        import odarms
        with tempfile.TemporaryDirectory() as t:
            a = (np.arange(28 * 9 * 7) % 255).astype(np.uint8).reshape(28, 9, 7)
            odarms.write_zarr(Path(t) / "R0.zarr", a)
            np.testing.assert_array_equal(odarms.read_zarr(Path(t) / "R0.zarr"), a)


@unittest.skipIf(NEEDS, "needs numpy and scipy")
class ScoreTest(unittest.TestCase):
    def test_label_offset_moves_labels_and_drops_the_vacated_edge(self):
        import odscore
        idx, ok = odscore._axis(0, 6, 6, 6, 1.0, -2)        # pixel p takes surface pixel p + 2
        self.assertEqual(idx.tolist(), [2, 3, 4, 5, 5, 5])
        self.assertEqual(ok.tolist(), [True, True, True, True, False, False])
        idx, ok = odscore._axis(2, 5, 10, 5, 0.5, 1)        # half-resolution labels, moved by +1
        self.assertEqual(idx.tolist(), [0, 1, 1])
        self.assertTrue(ok.all())

    @unittest.skipIf(zarr is None, "needs zarr")
    def test_labels_on_map_with_texture_offset(self):
        import odscore
        with tempfile.TemporaryDirectory() as t:
            lab = np.zeros((40, 50), np.uint8)
            lab[20, 30] = 1
            for name, arr in (("inklabels.zarr", lab), ("supervision.zarr", np.ones_like(lab))):
                g = zarr.open_group(str(Path(t) / name), mode="w")
                g.create_array("2", data=arr, chunks=arr.shape)
            ink, sup = odscore.labels_on_map(Path(t) / "inklabels.zarr", Path(t) / "supervision.zarr", (40, 50),
                                             (10, 30, 20, 45), (-6, -7))
            self.assertEqual(ink.shape, (20, 25))
            self.assertEqual(list(zip(*np.nonzero(ink))), [(20 - 6 - 10, 30 - 7 - 20)])
            self.assertTrue(sup[:, :23].all() and not sup[:, 23:].any())    # columns 43 and 44 have no source
            ink0, sup0 = odscore.labels_on_map(Path(t) / "inklabels.zarr", Path(t) / "supervision.zarr", (40, 50),
                                               (10, 30, 20, 45))
            self.assertEqual(list(zip(*np.nonzero(ink0))), [(10, 10)])
            self.assertTrue(sup0.all())

    def test_score_arm_reads_control_and_difference(self):
        import odscore
        rng = np.random.default_rng(3)
        ink = np.zeros((300, 300), bool)
        ink[:, ::7] = True
        ink[::5, :] = True
        sup = np.ones_like(ink)
        good = np.where(ink, 200, 50).astype(np.uint8) + rng.integers(0, 40, ink.shape).astype(np.uint8)
        noisy = np.where(ink, 120, 100).astype(np.uint8) + rng.integers(0, 60, ink.shape).astype(np.uint8)
        rev = rng.integers(1, 255, ink.shape).astype(np.uint8)
        row = odscore.score_arm(noisy, ink, sup, control=rev, ref=good, draws=50, seed=0, inner=16)
        self.assertLess(row["auc"], 1.0)
        self.assertAlmostEqual(row["control"], 0.5, delta=0.05)
        self.assertLess(row["vs_R0"]["difference"], 0)
        lo, hi = row["vs_R0"]["ci95"]
        self.assertLess(hi, 0)
        self.assertLessEqual(lo, row["vs_R0"]["difference"])
        best = odscore.score_arm(good, ink, sup, inner=16)
        self.assertEqual(best["auc"], 1.0)
        self.assertNotIn("vs_R0", best)


@unittest.skipIf(NEEDS, "needs numpy and scipy")
class CliTest(unittest.TestCase):
    def run_cli(self, *args, env=None):
        e = dict(os.environ, **(env or {}))
        return subprocess.run([sys.executable, str(TOOL / "offsetdiag.py"), *args], capture_output=True, text=True,
                              env=e, cwd=str(ROOT))

    def test_help_and_missing_inputs(self):
        r = self.run_cli("--help")
        self.assertEqual(r.returncode, 0)
        for cmd in ("fetch", "validate", "render", "measure", "arms", "score"):
            self.assertIn(cmd, r.stdout)
        with tempfile.TemporaryDirectory() as t:
            r = self.run_cli("arms", "0841-w00", "--work", t)
            self.assertEqual(r.returncode, 3)
            self.assertIn("run render 0841-w00 first", r.stderr)
            r = self.run_cli("score", "--work", t, "--model", "rv3")
            self.assertEqual(r.returncode, 3)
            self.assertIn("no maps named MODEL_KEY_ARM.tif", r.stderr)
            r = self.run_cli("render", "nope", "--work", t)
            self.assertEqual(r.returncode, 3)
            self.assertIn("unknown segment", r.stderr)

    def test_infer_dry_run_lists_every_unmapped_arm(self):
        with tempfile.TemporaryDirectory() as t:
            for arm in ("P0", "R0", "SNAP"):
                (Path(t) / "arms" / "0841-w00" / f"{arm}.zarr").mkdir(parents=True)
            (Path(t) / "maps").mkdir()
            for f in ("rv3_0841-w00_R0.tif", "rv3_0841-w00_R0_reverse.tif"):
                (Path(t) / "maps" / f).write_bytes(b"")
            r = subprocess.run(["bash", str(TOOL / "infer.sh"), "ck.pth", t, "rv3"], capture_output=True, text=True,
                               env=dict(os.environ, DRY_RUN="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = [x for x in r.stdout.splitlines() if "inference.infer" in x]
            self.assertEqual(len(lines), 2)
            self.assertTrue(all("--layer-start 6 --layer-end 23" in x and "--direction both" in x for x in lines))
            self.assertIn("rv3_0841-w00_SNAP.tif", r.stdout)
            self.assertIn("DONE 3 arms, 1 already mapped", r.stdout)
            r = subprocess.run(["bash", str(TOOL / "infer.sh"), "ck.pth", t], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
