import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "fibercheck"))

try:
    import numpy as np
    import fibercheck as FC
except ImportError:          # the checker needs numpy; CI without it skips these tests
    np = FC = None


@unittest.skipIf(np is None, "needs numpy")
class FibercheckTest(unittest.TestCase):
    def test_upsample_hits_vertices_and_midpoints(self):
        a = np.arange(2 * 2 * 3, dtype=float).reshape(2, 2, 3)
        u = FC.upsample(a, 2)
        self.assertEqual(u.shape, (3, 3, 3))
        np.testing.assert_allclose(u[0, 0], a[0, 0])
        np.testing.assert_allclose(u[2, 2], a[1, 1])
        np.testing.assert_allclose(u[1, 1], a.mean((0, 1)))

    def test_auto_k_is_vertex_spacing_at_the_level(self):
        yy, xx = np.mgrid[0:5, 0:5].astype(float) * 20
        xyz = np.stack([xx, yy, np.zeros_like(xx)], -1)
        valid = np.ones((5, 5), bool)
        self.assertEqual(FC.auto_k(xyz, valid, 2), 5)
        self.assertEqual(FC.auto_k(xyz, valid, 0), 12)          # clamped
        self.assertEqual(FC.auto_k(xyz, np.zeros((5, 5), bool), 2), 5)

    def test_prompt_matches_the_frozen_fiber_prompt(self):
        frozen = ROOT / "scripts" / "h2h" / "fiberjudge.py"
        if not frozen.is_file():
            self.skipTest("the frozen fiber procedure is in the private workbench only")
        src = frozen.read_text()
        ns = {}
        start = src.index("PROMPT = (")
        exec(src[start:src.index(")\n", start) + 2], ns)
        self.assertEqual(FC.PROMPT, ns["PROMPT"])

    def test_normals_of_a_plane(self):
        yy, xx = np.mgrid[0:6, 0:6].astype(float)
        xyz = np.stack([xx, yy, np.full_like(xx, 5.0)], -1)
        n, ok = FC.normals(xyz, np.ones((6, 6), bool))
        self.assertTrue(ok[1:-1, 1:-1].all() and not ok[0].any())
        np.testing.assert_allclose(np.abs(n[ok][:, 2]), 1.0)

    def test_ct_reads_local_zarr_v2_and_zero_outside(self):
        try:
            import numcodecs
        except ImportError:
            self.skipTest("numcodecs not installed")
        with tempfile.TemporaryDirectory() as d:
            lvl = Path(d, "vol.zarr", "0")
            lvl.mkdir(parents=True)
            data = np.arange(4 * 4 * 4, dtype=np.uint8).reshape(4, 4, 4)
            codec = numcodecs.Zlib()
            (lvl / ".zarray").write_text(json.dumps({"shape": [4, 4, 4], "chunks": [2, 2, 2], "dtype": "|u1",
                                                     "compressor": codec.get_config(), "order": "C",
                                                     "fill_value": 0, "zarr_format": 2}))
            for z in range(2):
                for y in range(2):
                    for x in range(2):
                        blk = np.ascontiguousarray(data[2 * z:2 * z + 2, 2 * y:2 * y + 2, 2 * x:2 * x + 2])
                        (lvl / f"{z}.{y}.{x}").write_bytes(codec.encode(blk.tobytes()))
            ct = FC.CT(Path(d, "vol.zarr"), 0, cache=Path(d, "cache"))
            q = np.array([[0, 0, 0], [3, 2, 1], [1, 3, 3], [9, 0, 0], [-1, 0, 0]])
            v = ct.values(q)
            np.testing.assert_array_equal(v[:3], [data[0, 0, 0], data[3, 2, 1], data[1, 3, 3]])
            np.testing.assert_array_equal(v[3:], [0, 0])

    def test_phase_scramble_keeps_spectrum_and_moments(self):
        rng = np.random.default_rng(1)
        a = np.cumsum(rng.standard_normal((32, 32)), 1)
        b = FC.phase_scramble(a, 3)
        self.assertAlmostEqual(float(b.mean()), float(a.mean()), places=6)
        self.assertAlmostEqual(float(b.std()), float(a.std()), places=4)
        self.assertGreater(np.abs(a - b).mean(), 0.1)

    def test_color_marks_holes_and_no_fiber(self):
        m = np.array([[np.nan, 0.3, 0.75, 1.0]])
        rgb = FC.color(m)
        self.assertEqual(tuple(rgb[0, 0]), (24, 24, 28))
        self.assertEqual(tuple(rgb[0, 1]), (110, 110, 110))
        self.assertEqual(tuple(rgb[0, 3]), (253, 231, 37))

    def test_jump_hint_needs_bright_neighbors(self):
        ps = [{"r": 0, "c": 0, "evidence": 0.9}, {"r": 0, "c": 28, "evidence": 0.3},
              {"r": 0, "c": 56, "evidence": 0.95}, {"r": 28, "c": 28, "evidence": 0.6}]
        self.assertEqual(FC.jump_hints(ps, 28), [])
        ps[3]["evidence"] = 0.85
        self.assertEqual(FC.jump_hints(ps, 28), [{"r": 0, "c": 28}])

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "fiber_direction needs scipy")
    def test_fiber_direction(self):
        stripes = np.tile(np.sin(np.arange(64) / 2.0)[:, None], (1, 64))   # each row constant: horizontal strands
        d, coh = FC.fiber_direction(stripes)
        self.assertEqual(d, "horizontal")
        self.assertGreater(coh, 0.9)
        self.assertEqual(FC.fiber_direction(stripes.T)[0], "vertical")


if __name__ == "__main__":
    unittest.main()
