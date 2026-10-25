import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy  # noqa: F401
    import tifffile  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False

ROOT = Path(__file__).resolve().parents[1]


def _sheets_volume(np, n_sheets=7, pitch=8, h=96, w=96, smear=0.0, seed=0):
    """A z y x prediction volume with flat sheets every pitch voxels, each with its own random ink blobs; smear
    spreads each sheet's prediction along z with a Gaussian of that many voxels."""
    from kit.phantom import gaussian_blur
    rng = np.random.default_rng(seed)
    depth = (n_sheets + 1) * pitch
    vol = np.zeros((depth, h, w))
    for i in range(n_sheets):
        ink = gaussian_blur((rng.random((h, w)) < 0.03).astype(float), 2.0)
        ink = (ink - ink.mean()) / ink.std()
        z0 = (i + 1) * pitch
        if smear:
            z = np.arange(depth)[:, None, None]
            vol += np.exp(-0.5 * ((z - z0) / smear) ** 2) * ink[None]
        else:
            vol[z0] += ink
    return vol + 0.05 * rng.standard_normal(vol.shape), (n_sheets // 2 + 1) * pitch


def _flat_mesh(np, folder, z0, h=96, w=96):
    import tifffile
    folder.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    tifffile.imwrite(str(folder / "x.tif"), xx)
    tifffile.imwrite(str(folder / "y.tif"), yy)
    tifffile.imwrite(str(folder / "z.tif"), np.full((h, w), float(z0), np.float32))
    (folder / "meta.json").write_text(json.dumps({"format": "tifxyz", "scale": [1.0, 1.0], "type": "seg"}))
    return folder


@unittest.skipUnless(HAVE, "needs numpy and tifffile")
class SheetCheckTest(unittest.TestCase):
    def test_demo_sharp_passes_every_false_kind_fails(self):
        from kit import sheetcheck
        for seed in range(4):
            res = sheetcheck.demo(seed)
            self.assertEqual(res["sharp"]["verdict"], "PASS", seed)
            for kind in ("smeared", "shared", "edge", "void"):
                self.assertEqual(res[kind]["verdict"], "FAIL", (seed, kind))
            self.assertEqual(res["smeared"]["kind"], "smeared")
            self.assertEqual(res["shared"]["kind"], "shared")

    def test_identical_maps_fail_independent_maps_pass(self):
        import numpy as np
        from kit import sheetcheck
        rng = np.random.default_rng(1)
        m = rng.standard_normal((128, 128))
        same = sheetcheck.check({0: m, 1: m, -1: m + 0.01 * rng.standard_normal(m.shape)})
        self.assertEqual(same["verdict"], "FAIL")
        self.assertGreater(same["r1"], 0.99)
        indep = sheetcheck.check({k: rng.standard_normal((128, 128)) for k in (-1, 0, 1)})
        self.assertEqual(indep["verdict"], "PASS")
        self.assertLess(abs(indep["r1"]), 0.1)

    def test_shading_shared_by_every_sheet_is_removed_by_the_high_pass(self):
        import numpy as np
        from kit import sheetcheck
        rng = np.random.default_rng(2)
        yy, xx = np.mgrid[0:256, 0:256]
        ramp = 5.0 * (xx / 256.0)                               # slow brightness drift every sheet shares
        maps = {k: rng.standard_normal((256, 256)) + ramp for k in (-1, 0, 1)}
        self.assertEqual(sheetcheck.check(maps, sigma=0)["verdict"], "FAIL")
        self.assertEqual(sheetcheck.check(maps)["verdict"], "PASS")

    def test_only_the_map_on_the_sheet_runs_edge_and_void_only(self):
        import numpy as np
        from kit import sheetcheck
        m = np.random.default_rng(3).standard_normal((64, 64))
        r = sheetcheck.check({0: m})
        self.assertEqual(r["verdict"], "NO-SHIFTS")
        self.assertIsNone(r["r1"])

    def test_refusals(self):
        import numpy as np
        from kit import sheetcheck
        m = np.zeros((32, 32))
        with self.assertRaises(sheetcheck.SheetCheckError):
            sheetcheck.check({1: m, -1: m})
        with self.assertRaises(sheetcheck.SheetCheckError):
            sheetcheck.check({0: m, 1: np.zeros((16, 16))})
        with self.assertRaises(sheetcheck.SheetCheckError):
            sheetcheck.check({0: m}, mask=np.ones((8, 8)))
        with self.assertRaises(sheetcheck.SheetCheckError):
            sheetcheck._parse_map("on.tif")
        self.assertEqual(sheetcheck._parse_map("-1=in.tif"), (-1.0, "in.tif"))

    def test_summary_needs_windows_and_a_low_mean(self):
        from kit import sheetcheck
        good = {"verdict": "PASS", "r1": 0.2}
        bad = {"verdict": "FAIL", "r1": 0.8}
        self.assertEqual(sheetcheck.summary({f"w{i}": good for i in range(6)})["verdict"], "PASS")
        self.assertEqual(sheetcheck.summary({f"w{i}": good for i in range(5)})["verdict"], "FAIL")
        mixed = {f"w{i}": good for i in range(9)}
        mixed["w9"] = bad
        self.assertEqual(sheetcheck.summary(mixed)["verdict"], "PASS")
        mixed.update({"w10": bad, "w11": bad})
        self.assertEqual(sheetcheck.summary(mixed)["verdict"], "FAIL")
        self.assertEqual(sheetcheck.summary({f"w{i}": bad for i in range(8)})["verdict"], "FAIL")

    def test_volume_projection_sharp_passes_smeared_fails(self):
        import numpy as np
        from kit import sheetcheck
        with tempfile.TemporaryDirectory() as tmp:
            for smear, want in ((0.0, "PASS"), (6.0, "FAIL")):
                vol, z0 = _sheets_volume(np, smear=smear)
                mesh = _flat_mesh(np, Path(tmp) / f"mesh{smear:g}", z0)
                maps = sheetcheck.volume_maps(vol, str(mesh), pitch=8, half=1)
                self.assertEqual(sorted(maps), [-2.0, -1.0, 0.0, 1.0, 2.0])
                # the projection on the sheet reads that sheet's own ink
                sheet = vol[z0]
                inner = np.s_[2:-2, 2:-2]
                self.assertGreater(np.corrcoef(maps[0.0][inner].ravel(), sheet[inner].ravel())[0, 1], 0.9)
                r = sheetcheck.check(maps, sigma=8)
                self.assertEqual(r["verdict"], want, (smear, r["r"]))

    def test_trilinear_matches_a_linear_field(self):
        import numpy as np
        from kit import sheetcheck
        z, y, x = np.mgrid[0:6, 0:7, 0:8].astype(float)
        vol = 2 * z + 3 * y + 5 * x
        pts = np.array([[1.5, 2.25, 3.75], [0.0, 0.0, 0.0], [9.0, 1.0, 1.0]])   # x y z
        got = sheetcheck.trilinear(vol, pts, (0, 0, 0))
        self.assertAlmostEqual(got[0], 2 * 3.75 + 3 * 2.25 + 5 * 1.5)
        self.assertAlmostEqual(got[1], 0.0)
        self.assertTrue(np.isnan(got[2]))

    def test_cli_maps_and_summary_exit_codes(self):
        import numpy as np
        import tifffile
        rng = np.random.default_rng(4)
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            same = rng.standard_normal((96, 96)).astype(np.float32)
            for k in (-1, 0, 1):
                tifffile.imwrite(str(t / f"s{k}.tif"), same)
                tifffile.imwrite(str(t / f"i{k}.tif"), rng.standard_normal((96, 96)).astype(np.float32))
            base = [sys.executable, "-m", "kit", "sheetcheck", "maps"]
            run = lambda p: subprocess.run(base + [f"--map={k}={t}/{p}{k}.tif" for k in (-1, 0, 1)]  # noqa: E731
                                           + ["--json", "--name", p], cwd=ROOT, capture_output=True, text=True)
            ok, bad = run("i"), run("s")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(bad.returncode, 1, bad.stderr)
            (t / "ok.json").write_text(ok.stdout)
            s = subprocess.run([sys.executable, "-m", "kit", "sheetcheck", "summary", str(t / "ok.json"),
                                "--min-windows", "1", "--json"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(s.returncode, 0, s.stderr)
            self.assertEqual(json.loads(s.stdout)["summary"]["verdict"], "PASS")
            missing = subprocess.run(base + [f"--map=1={t}/i1.tif"], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)


if __name__ == "__main__":
    unittest.main()
