"""kit/selfcross.py: the self-intersection backends (villa's vc_tifxyz_selfcross, and its census kernel compiled here).

The loader rule, the backend choice, the commands and the report are checked with no villa code. The kernel tests
compile villa's census header and run it on the fixtures of tests/selfcross_fixtures.py, whose counts villa's own
vc_tifxyz_selfcross at 7154682e1 gave; they skip without a C++17 compiler or a copy of the header (KIT_SELFCROSS_HEADER,
or the kit home's cache from `python -m kit selfcross build`), since tests do not fetch it.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from kit import selfcross, vc3d  # noqa: E402

try:
    import numpy as np
    import selfcross_fixtures as fx
except ImportError:     # pragma: no cover
    np = None

import vc3d_fakes  # noqa: E402

REPORT_KEYS = ["tool", "backend", "kernel", "report_only", "surface", "clean_of_transverse_self_intersection", "note",
               "parameters", "grid_rows", "grid_cols", "census"]
# the keys villa's vc_tifxyz_selfcross writes (apps/src/vc_tifxyz_selfcross.cpp at 7154682e1)
VILLA_KEYS = {"tool", "report_only", "surface", "clean_of_transverse_self_intersection", "note", "parameters",
              "grid_rows", "grid_cols", "census"}
CENSUS_KEYS = {"diagonal", "triangles", "quads_dropped_for_edge_length", "pairs_tested", "transverse", "coplanar",
               "grazing", "transverse_contacts"}
CONTACT_KEYS = {"quad1", "quad2", "tri1", "tri2", "penetration_vx", "angle_deg", "site"}


def _real_header():
    """A copy of the census header that passes its sha256, or None (tests never fetch it)."""
    for cand in (os.environ.get(selfcross.ENV_HEADER),
                 selfcross.build_root(os.environ) / f"villa-{selfcross.VILLA_COMMIT[:9]}" / selfcross.HEADER_NAME):
        if cand and Path(cand).is_file():
            try:
                selfcross.header(str(cand), env={}, fetch=False)
                return str(cand)
            except selfcross.SelfcrossError:
                pass
    return None


@unittest.skipIf(np is None, "numpy is not installed")
class LoaderRule(unittest.TestCase):
    """The grid the kernel gets is the one VC3D's load_quad_from_tifxyz gives."""

    def load(self, grid, mask=None):
        with tempfile.TemporaryDirectory() as d:
            return selfcross.load_grid(fx.write(Path(d) / "s.tifxyz", grid, mask))

    def test_z_nonpositive_invalid_and_x_minus_one_kept(self):
        P = fx.blank(3, 4)
        fx.plane(P, 0, 3, 4, 5.0)
        P[0, 0, 2] = 0.0
        P[1, 1, 2] = -2.0
        P[2, 2, 0] = -1.0          # x = -1, z > 0: VC3D keeps it
        g = self.load(P)
        self.assertTrue((g[0, 0] == -1).all() and (g[1, 1] == -1).all())
        self.assertEqual(g[2, 2, 0], -1.0)
        self.assertEqual(g[2, 2, 2], 5.0)
        self.assertEqual(g.dtype, np.float32)

    def test_nan_stays(self):
        P = fx.blank(2, 2)
        fx.plane(P, 0, 2, 2, 5.0)
        P[0, 1, 0] = np.nan
        self.assertTrue(np.isnan(self.load(P)[0, 1, 0]))

    def test_mask_same_size_and_decimated(self):
        P = fx.blank(4, 4)
        fx.plane(P, 0, 4, 4, 5.0)
        m = np.full((4, 4), 255, np.uint8)
        m[1, 2] = 254
        g = self.load(P, m)
        self.assertTrue((g[1, 2] == -1).all())
        self.assertEqual(int((g[..., 2] == -1).sum()), 1)
        m2 = np.full((8, 8), 255, np.uint8)
        m2[5, 1] = 0               # one pixel of cell (2, 0)'s 2 x 2 block
        g = self.load(P, m2)
        self.assertTrue((g[2, 0] == -1).all())
        self.assertEqual(int((g[..., 2] == -1).sum()), 1)

    def test_mask_not_a_multiple_is_ignored(self):
        P = fx.blank(4, 4)
        fx.plane(P, 0, 4, 4, 5.0)
        g = self.load(P, np.zeros((5, 5), np.uint8))
        self.assertFalse((g == -1).any())


class Backends(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.env = {"KIT_HOME": str(self.d / "home")}

    def test_auto_prefers_villa_then_kernel(self):
        tools = vc3d_fakes.make_bin(self.d / "bin")
        self.assertEqual(selfcross.resolve("auto", tools, self.env), ("villa", None))
        bare = vc3d_fakes.make_bin(self.d / "bare", names=[vc3d.PROBE])
        name, why = selfcross.resolve("auto", bare, self.env)
        self.assertIsNone(name)
        self.assertIn("vc_tifxyz_selfcross is not in the VC3D build", why)
        self.assertIn("kit selfcross build", why)
        env = {**self.env, selfcross.ENV_BIN: str(vc3d_fakes.make_kernel(self.d / "k"))}
        self.assertEqual(selfcross.resolve("auto", bare, env), ("kernel", None))
        self.assertEqual(selfcross.resolve("kernel", tools, env), ("kernel", None))
        self.assertEqual(selfcross.resolve("villa", bare, env)[0], None)
        with self.assertRaises(selfcross.SelfcrossError):
            selfcross.resolve("numpy", tools, env)

    def test_bin_that_is_not_executable_is_refused(self):
        p = self.d / "notexe"
        p.write_text("x")
        b, why = selfcross.kernel_binary({**self.env, selfcross.ENV_BIN: str(p)})
        self.assertIsNone(b)
        self.assertIn("not an executable", why)

    def test_argv(self):
        tools = vc3d_fakes.make_bin(self.d / "bin")
        v = selfcross.argv("villa", "S", "R.json", tools, 4)
        self.assertEqual(v[1:], ["--surface", "S", "-o", "R.json", "--threads", "4"])
        k = selfcross.argv("kernel", "S", "R.json", threads=4, params={"maxedge": 30.0})
        self.assertEqual(k[:6], [sys.executable, "-m", "kit", "selfcross", "run", "--backend"])
        self.assertIn("--maxedge", k)
        self.assertNotIn("--cell", k)       # defaults are left to the backend

    def test_header_sha_is_checked(self):
        bad = self.d / "h.hpp"
        bad.write_text("// not villa's header\n")
        with self.assertRaises(selfcross.SelfcrossError) as cm:
            selfcross.header(str(bad), env=self.env)
        self.assertIn("refused", str(cm.exception))
        with self.assertRaises(selfcross.SelfcrossError) as cm:
            selfcross.header(None, env=self.env, fetch=False)
        self.assertIn("kit selfcross build", str(cm.exception))

    def test_build_refuses_a_wrong_header_before_compiling(self):
        bad = self.d / "h.hpp"
        bad.write_text("// not villa's header\n")
        with mock.patch.dict(os.environ, self.env):
            with self.assertRaises(selfcross.SelfcrossError):
                selfcross.build(given_header=str(bad), env=self.env)
            self.assertIsNone(selfcross.kernel_binary(self.env)[0])

    @unittest.skipIf(np is None, "numpy is not installed")
    def test_run_kernel_writes_villas_report_shape(self):
        exe = vc3d_fakes.make_kernel(self.d / "k")
        surf = fx.write(self.d / "s.tifxyz", *fx.named()["flat"])
        with mock.patch.dict(os.environ, {"FAKE_KERNEL": "dirty"}):
            rep = selfcross.run_kernel(surf, self.d / "r.json", threads=1, binary=exe)
        self.assertEqual(list(rep), REPORT_KEYS)
        self.assertTrue(VILLA_KEYS <= set(rep))
        self.assertEqual(json.loads((self.d / "r.json").read_text()), rep)
        self.assertEqual(rep["backend"], "kernel")
        self.assertEqual(rep["kernel"]["header_sha256"], selfcross.HEADER_SHA256)
        self.assertFalse(rep["clean_of_transverse_self_intersection"])
        self.assertEqual(selfcross.transverse(rep), 2)
        self.assertEqual(rep["parameters"], {"exclude": 1, "maxedge": 60.0, "cell": 40.0, "touch_tolerance": 1e-3,
                                             "diagonals": [0, 1]})
        self.assertEqual((rep["grid_rows"], rep["grid_cols"]), (12, 16))
        # every reader of villa's report reads it
        from kit import regioncrop
        self.assertEqual(regioncrop.parse_selfcross(rep)["transverse"], 2)

    @unittest.skipIf(np is None, "numpy is not installed")
    def test_run_kernel_refuses_bad_parameters_and_a_crash(self):
        exe = vc3d_fakes.make_kernel(self.d / "k")
        surf = fx.write(self.d / "s.tifxyz", *fx.named()["flat"])
        for bad in ({"cell": 0}, {"exclude": -1}, {"maxedge": float("nan")}):
            with self.assertRaises(selfcross.SelfcrossError):
                selfcross.run_kernel(surf, self.d / "r.json", binary=exe, **bad)
        with mock.patch.dict(os.environ, {"FAKE_KERNEL": "crash"}):
            with self.assertRaises(selfcross.SelfcrossError):
                selfcross.run_kernel(surf, self.d / "r.json", binary=exe)
        self.assertFalse((self.d / "r.json").exists())

    @unittest.skipIf(np is None, "numpy is not installed")
    def test_cli_run_through_a_fake_kernel(self):
        exe = vc3d_fakes.make_kernel(self.d / "k")
        surf = fx.write(self.d / "s.tifxyz", *fx.named()["flat"])
        env = {**os.environ, **self.env, selfcross.ENV_BIN: str(exe), "VC_BIN": str(self.d / "nobin"),
               "FAKE_KERNEL": "dirty"}
        (self.d / "nobin").mkdir()
        cmd = [sys.executable, "-m", "kit", "selfcross", "run", "--surface", str(surf), "-o", str(self.d / "r.json")]
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("2 contacts on diagonal 0", p.stdout)
        kernel = json.loads((self.d / "r.json").read_text())["kernel"]
        self.assertEqual((kernel["given"], kernel["unverified"]), (selfcross.ENV_BIN, True))   # not built here
        p = subprocess.run(cmd + ["--fail-on-crossing"], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 3, p.stderr)
        env.pop(selfcross.ENV_BIN)
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("no self-intersection backend", p.stderr)

    def test_census_without_a_backend_says_why(self):
        bare = vc3d_fakes.make_bin(self.d / "bare", names=[vc3d.PROBE])
        got = selfcross.census("S", self.d / "r.json", tools=bare, env=self.env)
        self.assertIsNone(got["backend"])
        self.assertIn("no self-intersection backend", got["error"])
        with self.assertRaises(selfcross.SelfcrossError):
            selfcross.report_json("S", bare, env=self.env)


@unittest.skipIf(np is None, "numpy is not installed")
@unittest.skipUnless(selfcross.find_compiler(), "no C++17 compiler")
class Kernel(unittest.TestCase):
    """villa's census kernel, compiled here, on the fixtures villa's own tool counted."""

    @classmethod
    def setUpClass(cls):
        cls.header = _real_header()
        if cls.header is None:
            raise unittest.SkipTest("no copy of villa's census header (set KIT_SELFCROSS_HEADER, or run "
                                    "python -m kit selfcross build once)")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        cls.env = {"KIT_HOME": str(cls.d / "home"), "PATH": os.environ.get("PATH", "")}
        cls.rec = selfcross.build(given_header=cls.header, env=cls.env)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_build_record_and_reuse(self):
        self.assertEqual(self.rec["header_sha256"], selfcross.HEADER_SHA256)
        self.assertEqual(self.rec["villa_commit"], selfcross.VILLA_COMMIT)
        self.assertIn("GPL-3.0", self.rec["licence"])
        self.assertTrue(selfcross.build(given_header=self.header, env=self.env).get("reused"))
        b, rec = selfcross.kernel_binary(self.env)
        self.assertEqual(str(b), self.rec["binary"])

    def test_named_fixtures_match_villas_counts(self):
        binary = Path(self.rec["binary"])
        for name, (grid, mask) in fx.named().items():
            with self.subTest(name=name):
                surf = fx.write(self.d / f"{name}.tifxyz", grid, mask)
                rep = selfcross.run_kernel(surf, self.d / f"{name}.json", threads=2, binary=binary)
                self.assertEqual(fx.counts(rep), fx.VILLA[name])
                for d in rep["census"]:
                    self.assertEqual(set(d), CENSUS_KEYS)
                    for c in d["transverse_contacts"]:
                        self.assertEqual(set(c), CONTACT_KEYS)
                self.assertEqual(rep["clean_of_transverse_self_intersection"], sum(fx.VILLA[name][0]) == 0)

    def test_thread_count_does_not_change_the_report(self):
        binary = Path(self.rec["binary"])
        surf = fx.write(self.d / "fold.tifxyz", *fx.named()["fold_through_self"])
        a = selfcross.run_kernel(surf, self.d / "a.json", threads=1, binary=binary)
        b = selfcross.run_kernel(surf, self.d / "b.json", threads=4, binary=binary)
        self.assertEqual([d["transverse_contacts"] for d in a["census"]],
                         [d["transverse_contacts"] for d in b["census"]])

    def test_controls_catch_a_wrong_loader(self):
        """Ignoring the mask changes the counts: the fixture comparison can fail."""
        binary = Path(self.rec["binary"])
        grid, mask = fx.named()["mask_same_size"]
        surf = fx.write(self.d / "nomask.tifxyz", grid, None)
        rep = selfcross.run_kernel(surf, self.d / "nomask.json", threads=2, binary=binary)
        self.assertNotEqual(fx.counts(rep), fx.VILLA["mask_same_size"])


if __name__ == "__main__":
    unittest.main()
