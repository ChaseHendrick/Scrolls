"""scripts/umbilicus/lineends.py: the Center Finder's trim of center line ends that leave the scroll in the masked CT.

Synthetic masked scans only (no network, no numpy): a disc of papyrus in slices 50 to 149 of a 200-slice scan."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


# the same module name build_lines.py loads it under, so both share one copy
le = load("umbilicus_lineends", ROOT / "scripts" / "umbilicus" / "lineends.py")

SHAPE, CHUNKS = [200, 64, 64], [64, 32, 32]
UM = 1000.0  # 1 mm voxels at level 0 and f = 1, so FAR_MM is 4 voxels


def solid_tile(inside):
    def tile(zi, cy, cx):
        _, ch_y, ch_x = CHUNKS
        return bytes(7 if (y < SHAPE[1] and x < SHAPE[2] and inside(zi, y, x)) else 0
                     for y in range(cy * ch_y, (cy + 1) * ch_y) for x in range(cx * ch_x, (cx + 1) * ch_x))
    return tile


def disc(z, y, x):
    return 50 <= z < 150 and (y - 32) ** 2 + (x - 32) ** 2 <= 15 ** 2


def scan(inside=disc):
    return le.Slices(le.Volume(SHAPE, CHUNKS, solid_tile(inside)), 1, UM / 1000), 0


def doc(zs, x=lambda z: 32, extra=True):
    cps = [dict({"x": float(x(z)), "y": 32.0, "z": float(z)}, **({"tag": f"p{z}"} if extra else {})) for z in zs]
    return {"control_points": cps,
            "metadata": {"source_volume": "PHerc0001/volumes/20250101000000-1000.0um-1.2m-113keV-masked.zarr",
                         "voxelsize_um": UM, "made_by": "test"}}


class Trim(unittest.TestCase):
    def trim(self, d, sc=None):
        res, why = le.check_line(le._points(d), sc or scan())
        return le.trim_doc(d, res, why)

    def test_ends_in_slices_with_no_scroll_are_cut(self):
        # 20 points every 10 slices; z 0 to 40 and 150 to 190 have no scroll; each end zone holds 5 points
        out = self.trim(doc(range(0, 200, 10)))
        t = out["metadata"]["papyrus_trim"]
        self.assertTrue(t["tested"])
        self.assertEqual([p["z"] for p in out["control_points"]], [float(z) for z in range(50, 150, 10)])
        self.assertEqual((t["points_before"], t["points_after"]), (20, 10))
        self.assertEqual((t["low"]["points"], t["low"]["empty_slices"], t["low"]["z_voxels"]), (5, 5, 50.0))
        self.assertEqual((t["high"]["points"], t["high"]["z_mm"]), (5, 50.0))
        self.assertEqual(t["low"]["path_mm"], 50.0)
        self.assertEqual(t["level"], 0)
        self.assertIn("convex hull", t["rule"])

    def test_inside_line_is_unchanged(self):
        d = doc(range(60, 140, 5))
        out = self.trim(d)
        self.assertEqual(out["control_points"], d["control_points"])
        t = out["metadata"]["papyrus_trim"]
        self.assertEqual((t["low"]["points"], t["high"]["points"]), (0, 0))
        self.assertNotIn("z_mm", t["low"])
        self.assertIn("nothing outside", le._say(dict(t, file="a.json")))

    def test_sideways_run_past_the_outline_is_cut_and_measured(self):
        # inside the scroll's slices, but the two lowest points sit 30 voxels off center: 13 past the disc's edge
        d = doc(range(60, 140, 5), x=lambda z: 62 if z < 70 else 32)
        out = self.trim(d)
        t = out["metadata"]["papyrus_trim"]
        self.assertEqual(t["low"]["points"], 2)
        self.assertEqual(t["low"]["empty_slices"], 0)
        self.assertGreater(t["low"]["max_mm_past_outline"], 4.0)
        self.assertEqual(out["control_points"][0]["z"], 70.0)
        self.assertEqual(t["high"]["points"], 0)

    def test_an_excursion_that_comes_back_is_cut_with_the_end(self):
        d = doc(range(60, 140, 5), x=lambda z: 62 if z == 70 else 32)  # point 3 out, points 1, 2 in
        t = self.trim(d)["metadata"]["papyrus_trim"]
        self.assertEqual((t["low"]["points"], t["low"]["outside"]), (3, 1))

    def test_within_four_mm_of_the_outline_is_kept(self):
        d = doc(range(60, 140, 5), x=lambda z: 32 + 15 + 3 if z < 70 else 32)  # 3 voxels past the papyrus
        t = self.trim(d)["metadata"]["papyrus_trim"]
        self.assertEqual(t["low"]["points"], 0)

    def test_the_middle_half_is_never_cut(self):
        d = doc(range(60, 140, 5), x=lambda z: 62 if z == 95 else 32)  # outside, but in the middle
        out = self.trim(d)
        self.assertEqual(len(out["control_points"]), 16)

    def test_points_keep_their_order_and_keys(self):
        d = doc(range(0, 200, 10))
        d["control_points"].reverse()
        out = self.trim(d)
        self.assertEqual([p["z"] for p in out["control_points"]], [float(z) for z in range(140, 40, -10)])
        self.assertEqual(out["control_points"][0]["tag"], "p140")
        self.assertEqual(out["metadata"]["made_by"], "test")
        self.assertNotIn("papyrus_trim", d["metadata"])  # the input is not changed

    def test_failed_checks_cut_nothing(self):
        # middle point outside: frame in doubt
        d = doc(range(0, 200, 10), x=lambda z: 62)
        t = self.trim(d)["metadata"]["papyrus_trim"]
        self.assertFalse(t["tested"])
        self.assertIn("middle point", t["why"])
        self.assertEqual(t["points_after"], 20)
        # air not zero (an unmasked scan): the far corner reads as inside
        out = self.trim(doc(range(0, 200, 10)), scan(lambda z, y, x: True))
        self.assertFalse(out["metadata"]["papyrus_trim"]["tested"])
        self.assertIn("corner", out["metadata"]["papyrus_trim"]["why"])
        self.assertEqual(len(out["control_points"]), 20)
        # too short to test
        self.assertFalse(self.trim(doc([60, 70]))["metadata"]["papyrus_trim"]["tested"])

    def test_a_scan_that_cannot_be_opened_cuts_nothing(self):
        self.assertEqual(le.open_scan("PHerc0001/volumes/novoxelsize.zarr")[0], None)
        out = le.trim_doc(doc(range(0, 200, 10)), *le.check_line([], (None, "no scan")))
        self.assertEqual(out["metadata"]["papyrus_trim"]["why"], "no scan")
        self.assertEqual(len(out["control_points"]), 20)


class Run(unittest.TestCase):
    def test_trim_writes_copies_and_opens_each_scan_once(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "src", Path(d) / "out"
            src.mkdir()
            (src / "a_umbilicus.json").write_text(json.dumps(doc(range(0, 200, 10))))
            (src / "b_umbilicus.json").write_text(json.dumps(doc(range(60, 140, 5))))
            opened = []
            rows = le.run(sorted(src.iterdir()), out=out, opener=lambda v: opened.append(v) or scan())
            self.assertEqual(len(opened), 1)
            self.assertEqual([r["points_after"] for r in rows], [10, 16])
            a = json.loads((out / "a_umbilicus.json").read_text())
            self.assertEqual(len(a["control_points"]), 10)
            self.assertEqual(json.loads((src / "a_umbilicus.json").read_text())["control_points"][0]["z"], 0.0)
            self.assertTrue((out / "b_umbilicus.json").exists())

    def test_check_writes_nothing_and_a_file_without_a_scan_is_untested(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a_umbilicus.json"
            dd = doc(range(0, 200, 10))
            del dd["metadata"]["source_volume"]
            f.write_text(json.dumps(dd))
            rows = le.run([f], opener=lambda v: self.fail("no scan to open"))
            self.assertFalse(rows[0]["tested"])
            self.assertIn("--volume", rows[0]["why"])
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["a_umbilicus.json"])

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a_umbilicus.json"
            f.write_text(json.dumps(doc(range(0, 200, 10))))
            rep = Path(d) / "r.json"
            with mock.patch.object(le, "open_scan", lambda v: scan()), mock.patch("builtins.print"), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(le.main(["trim", str(f), "--out", str(Path(d) / "o"), "--report", str(rep)]), 0)
                with self.assertRaises(SystemExit):
                    le.main(["trim", str(f)])                       # no --out
                with self.assertRaises(SystemExit):
                    le.main(["trim", str(f), "--out", d])            # would overwrite the input
            self.assertEqual(json.loads(rep.read_text())[0]["points_after"], 10)
            self.assertEqual(len(json.loads((Path(d) / "o" / f.name).read_text())["control_points"]), 10)


class SameTestAsUmbilici(unittest.TestCase):
    def test_build_lines_uses_this_module(self):
        bl = load("umbilici_build_lines", ROOT / "spaces" / "umbilici" / "tools" / "build_lines.py")
        for name in ("outside_ends", "check_line", "open_slices", "Slices", "Volume", "hull"):
            self.assertIs(getattr(bl, name), getattr(le, name), name)
        self.assertEqual((bl.FAR_MM, bl.END_SHARE, bl.LEVEL), (le.FAR_MM, le.END_SHARE, le.LEVEL))


if __name__ == "__main__":
    unittest.main()
