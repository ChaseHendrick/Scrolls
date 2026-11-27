"""kit framecheck: gpchain's frame rule on synthetic pieces, renders and CT (27 Nov 2026)."""
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    import numpy as np
    import tifffile
except ImportError:  # pragma: no cover
    np = None

from kit import framecheck

CH = 32


def write_volume(root, vol):
    """A zarr v2 level 0, uncompressed, chunks CH^3, (z, y, x) uint8."""
    lv = Path(root) / "0"
    lv.mkdir(parents=True)
    (lv / ".zarray").write_text(json.dumps({"zarr_format": 2, "shape": list(vol.shape), "chunks": [CH] * 3,
                                            "dtype": "|u1", "compressor": None, "fill_value": 0, "order": "C",
                                            "filters": None, "dimension_separator": "/"}))
    for z in range(0, vol.shape[0], CH):
        for y in range(0, vol.shape[1], CH):
            for x in range(0, vol.shape[2], CH):
                blk = np.zeros((CH, CH, CH), np.uint8)
                part = vol[z:z + CH, y:y + CH, x:x + CH]
                blk[:part.shape[0], :part.shape[1], :part.shape[2]] = part
                d = lv / str(z // CH) / str(y // CH)
                d.mkdir(parents=True, exist_ok=True)
                (d / str(x // CH)).write_bytes(blk.tobytes())
    return Path(root)


def write_piece(folder, grid, scale):
    folder = Path(folder)
    folder.mkdir(parents=True)
    for k, c in enumerate("xyz"):
        tifffile.imwrite(folder / f"{c}.tif", grid[..., k].astype(np.float32))
    (folder / "meta.json").write_text(json.dumps({"format": "tifxyz", "scale": [scale, scale], "type": "seg"}))
    return folder


@unittest.skipIf(np is None, "numpy and tifffile are needed")
class FrameCheck(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        rng = np.random.default_rng(0)
        # smooth random CT: texture on the scale of a few voxels, so a one-cell shift decorrelates it
        z, y, x = np.meshgrid(*(np.arange(96),) * 3, indexing="ij")
        v = (128 + 50 * np.sin(x / 2.3 + y / 3.1) * np.cos(z / 2.7 - x / 4.1) + 30 * np.sin(y / 1.9 + z / 3.7)
             + rng.normal(0, 4, x.shape))
        self.ct = np.clip(v, 1, 255).astype(np.uint8)
        self.vol = write_volume(self.d / "v.zarr", self.ct)
        # a slanted sheet at x = 40 + 0.2 y, nodes every 2 voxels (scale 0.5), rows along z, columns along y
        r, c = np.meshgrid(np.arange(30), np.arange(30), indexing="ij")
        g = np.stack([40 + 0.2 * (10 + 2.0 * c), 10 + 2.0 * c, 10 + 2.0 * r], -1).astype(np.float64)
        self.piece = write_piece(self.d / "p.tifxyz", g, 0.5)
        self.layers = self.render(g, 0.5)

    def tearDown(self):
        shutil.rmtree(self.d)

    def render(self, g, s, layers=8, rim=True):
        """What vc_render_tifxyz would write: the CT along the normal (+x), the outer half node cell empty."""
        v = np.ones((30, 30), bool)
        H = W = int(round(30 / s))
        ok = framecheck.px_valid(v, (H, W), s)
        rr, cc = np.nonzero(ok)
        xyz = framecheck.px_xyz(g, rr, cc, s)
        vol = framecheck.ChunkVolume(str(self.vol))
        out = np.zeros((layers, H, W), np.uint8)
        for k in range(layers):
            off = np.array([k - (layers - 1) / 2, 0, 0])
            out[k][rr, cc] = np.clip(np.rint(vol.sample(xyz + off)), 1, 255)
        if rim:
            out[:, ok & ~framecheck.erode(ok, int(np.ceil(0.5 / s)))] = 0
        return out

    def run_check(self, piece=None, layers=None, **kw):
        return framecheck.check(piece or self.piece, self.layers if layers is None else layers,
                                framecheck.ChunkVolume(str(self.vol)), n=5000, **kw)

    def test_correct_render_passes(self):
        res = self.run_check()
        self.assertTrue(res["ok"], res)
        self.assertGreater(res["r"], 0.99)
        self.assertEqual(res["rim"]["at_edge"], 1.0)
        self.assertEqual(res["mid_layers"], [3, 4])

    def test_planted_frame_errors_fail(self):
        g, _, _ = framecheck.load_piece(self.piece)
        wrong = g.copy()
        wrong[..., :3] *= 7.91 / 8.64                      # a wrong voxel size
        scaled = write_piece(self.d / "wrong.tifxyz", wrong, 0.5)
        for name, kw in (("voxel", {"piece": scaled}),
                         ("shift", {"layers": np.roll(self.layers, 2, axis=1)}),   # one node cell (2 px)
                         ("flip", {"layers": self.layers[:, ::-1, :]}),
                         ("transpose", {"layers": np.ascontiguousarray(self.layers.transpose(0, 2, 1))})):
            res = self.run_check(**kw)
            self.assertFalse(res["ok"], name)
            self.assertLess(res["r"] if res["r"] == res["r"] else 0, 0.95, name)

    def test_empty_pixels_inside_the_piece_fail_the_rim_gate(self):
        hole = self.layers.copy()
        hole[:, 25:35, 25:35] = 0
        res = self.run_check(layers=hole)
        self.assertGreater(res["r"], 0.95)
        self.assertLess(res["rim"]["at_edge"], 1.0)
        self.assertFalse(res["ok"])

    def test_window_reads_fewer_chunks_and_still_passes(self):
        full = framecheck.ChunkVolume(str(self.vol))
        framecheck.check(self.piece, self.layers, full, n=5000)
        win = framecheck.ChunkVolume(str(self.vol))
        res = framecheck.check(self.piece, self.layers, win, n=5000, window=12)
        self.assertTrue(res["ok"])
        self.assertLess(win.fetched, full.fetched)

    def test_trilinear_sample_matches_scipy(self):
        try:
            from scipy import ndimage
        except ImportError:
            self.skipTest("scipy not installed")
        rng = np.random.default_rng(1)
        p = rng.uniform(1, 94, (2000, 3))
        got = framecheck.ChunkVolume(str(self.vol)).sample(p)
        want = ndimage.map_coordinates(self.ct.astype(np.float32), [p[:, 2], p[:, 1], p[:, 0]], order=1)
        self.assertLess(float(np.abs(got - want).max()), 1e-3)

    def test_erode_matches_scipy(self):
        try:
            from scipy import ndimage
        except ImportError:
            self.skipTest("scipy not installed")
        m = np.zeros((20, 23), bool)
        m[2:18, 3:21] = True
        m[8:10, 5:7] = False
        for k in (1, 3):
            self.assertTrue((framecheck.erode(m, k) == ndimage.binary_erosion(m, iterations=k)).all(), k)

    def test_render_scale_maps_pixels_to_nodes(self):
        g, _, _ = framecheck.load_piece(self.piece)
        half = self.render(g, 1.0)                 # vc_render_tifxyz --scale 0.5 of this piece: 1 px per node
        self.assertEqual(half.shape[1:], (30, 30))
        res = self.run_check(layers=half, render_scale=0.5)
        self.assertTrue(res["ok"], res)
        self.assertGreater(res["r"], 0.95)
        self.assertLess(self.run_check(layers=half[:, ::-1, :], render_scale=0.5)["r"], 0.95)

    def test_px_valid_maps_pixel_centers_to_nodes(self):
        # nodes 3 x 4 with node row 2 invalid: only node cells of row 0 are whole; scale 0.6 puts pixel row 1's center
        # at node row 0.9 (cell 0, whole), where a center at p + 0.75 would land in cell 1 (broken)
        v = np.ones((3, 5), bool)
        v[2] = False
        out = framecheck.px_valid(v, (3, 6), 0.6)
        self.assertEqual(out.shape, (3, 6))
        self.assertEqual(out[:, 0].tolist(), [True, True, False])
        self.assertEqual(out[0].tolist(), [True, True, True, True, True, True])   # col 5: node 3.3, cell 3 whole
        self.assertFalse(framecheck.px_valid(v, (3, 9), 0.6)[0, 8])                # node 5.1: past the grid
        tall = framecheck.px_valid(np.ones((5, 3), bool), (8, 4), 0.5)             # more pixel rows than columns
        self.assertTrue(tall.all())
        wide = framecheck.px_valid(np.ones((3, 6), bool), (4, 4), 0.6)             # pixel row 3 at node 2.1: past the rows
        self.assertEqual(wide[:, 0].tolist(), [True, True, True, False])

    def test_refusals(self):
        bad = [({"layers": self.layers[0]}, "stack"), ({"layers": self.layers[:1]}, "stack"),
               ({"mid": [1, 2, 3]}, "mid"), ({"mid": [0, 8]}, "mid"), ({"mid": [-1, 2]}, "mid"),
               ]
        for kw, msg in bad:
            with self.assertRaises(framecheck.FrameError) as err:
                self.run_check(**kw)
            self.assertIn(msg, str(err.exception))
        two = self.run_check(layers=self.layers[3:5])
        self.assertTrue(two["ok"], two)
        self.assertEqual(two["mid_layers"], [0, 1])
        holed = self.layers.copy()
        holed[:, 25:35, 25:35] = 0
        g, v, s = framecheck.load_piece(self.piece)
        v2 = v.copy()
        v2[13:16, 13:16] = False                                     # nodes under the center: no valid pixel there
        with self.assertRaises(framecheck.FrameError) as err:
            framecheck.check((g, v2, s), holed, framecheck.ChunkVolume(str(self.vol)), n=100, window=2)
        self.assertIn("centered window", str(err.exception))
        with self.assertRaises(framecheck.FrameError) as err:
            framecheck.check((g, np.zeros_like(v), s), self.layers, framecheck.ChunkVolume(str(self.vol)), n=100)
        self.assertIn("shape does not match", str(err.exception))

    def test_volume_locations(self):
        self.assertEqual(framecheck.resolve_volume("s3://vesuvius-challenge-open-data/S/volumes/v.zarr"),
                         framecheck.OPEN_DATA + "/S/volumes/v.zarr")
        self.assertEqual(framecheck.resolve_volume("S/volumes/v.zarr/"), framecheck.OPEN_DATA + "/S/volumes/v.zarr")
        self.assertEqual(framecheck.resolve_volume(str(self.vol)), str(self.vol))
        for bad in ("", "not-a-volume"):
            with self.assertRaises(framecheck.FrameError):
                framecheck.resolve_volume(bad)
        with self.assertRaises(framecheck.FrameError):
            framecheck.ChunkVolume(str(self.vol), level=1)            # no level 1 in the test volume

    def test_a_render_with_no_empty_pixel_passes_the_rim_gate(self):
        g, _, _ = framecheck.load_piece(self.piece)
        res = self.run_check(layers=self.render(g, 0.5, rim=False))
        self.assertEqual((res["rim"]["share"], res["rim"]["at_edge"]), (0.0, 1.0))
        self.assertTrue(res["ok"], res)

    def test_cli_exit_codes(self):
        np.save(self.d / "good.npy", self.layers)
        np.save(self.d / "bad.npy", self.layers[:, ::-1, :])
        base = [str(self.piece), "--volume", str(self.vol), "--n", "4000"]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(framecheck.main([base[0], str(self.d / "good.npy")] + base[1:]), 0)
            self.assertEqual(framecheck.main([base[0], str(self.d / "bad.npy")] + base[1:]), 1)
            self.assertEqual(framecheck.main([base[0], str(self.d / "none.npy")] + base[1:]), 2)
        self.assertIn("PASS", out.getvalue())
        self.assertIn("FAIL", out.getvalue())


if __name__ == "__main__":
    unittest.main()
