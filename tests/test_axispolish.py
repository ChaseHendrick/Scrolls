"""kit axispolish: the coverage polish of a center line, on synthetic spirals only (no network, no scroll data)."""
import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

try:
    import numpy as np
except ImportError:
    np = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kit import axispolish, windcheck  # noqa: E402

UM = 8.64
MM = 1000.0 / UM


def _segs(centre, pitch=40.0, turns=12):
    return windcheck.segments([windcheck.spiral(centre, pitch, turns)])


def _spiral_grids(folder, centres, turns=12):
    """xy normal-grid files of a planted spiral per slice: {z: (cx, cy)}."""
    (Path(folder) / "xy").mkdir(parents=True, exist_ok=True)
    for z, (cx, cy) in centres.items():
        line = np.round(windcheck.spiral((cx, cy), 40.0, turns)).astype(int)
        axispolish.write_grid(Path(folder) / "xy" / f"{z:06d}.grid", [line], (0, 0, 1600, 1600))
    return Path(folder)


def _line(path, pts, **meta):
    doc = {"control_points": [{"x": x, "y": y, "z": z} for z, y, x in pts],
           "metadata": {"voxelsize_um": UM, "volume": "20250101000000-8.640um-test.zarr", **meta}}
    Path(path).write_text(json.dumps(doc))
    return Path(path)


@unittest.skipIf(np is None, "needs numpy")
class TestTheFrozenRule(unittest.TestCase):
    """The numbers and outputs of the frozen test's polish (rule version 1, 22 Oct 2026)."""

    def test_the_rule(self):
        self.assertEqual(axispolish.RULE, {"version": 1, "radius_mm": 8.0, "coarse_mm": 0.4, "fine_radius_mm": 0.5,
                                           "fine_mm": 0.05, "min_segments": 500, "window": 5})
        self.assertLessEqual(axispolish.EVERY, 100)

    def test_points_match_the_frozen_code(self):
        # pinned from the frozen polish (rule sha256 71d431b3) on these spirals
        segs = _segs((800.0, 700.0))
        want = {(800.0 + 2 * MM, 700.0): ((800.0, 705.7870370370371), 12.247425505119779, 8.347515324056243),
                (800.0 - 1.3 * MM, 700.0 + 0.7 * MM): ((800.0, 705.787037037037), 12.24742550511978,
                                                       9.315761211576138)}
        for guess, (pt, cov, gcov) in want.items():
            got = axispolish.polish_point(segs, guess, UM)
            self.assertAlmostEqual(got[0][0], pt[0], places=6)
            self.assertAlmostEqual(got[0][1], pt[1], places=6)
            self.assertAlmostEqual(got[1], cov, places=9)
            self.assertAlmostEqual(got[2], gcov, places=9)
            self.assertLess(math.hypot(got[0][0] - 800.0, got[0][1] - 700.0), 0.5 * MM)

    def test_a_line_matches_the_frozen_code_and_skips_a_thin_slice(self):
        guess = [(0.0, 700.0, 800.0 + 2 * MM), (300.0, 700.0, 800.0 + 2 * MM)]
        at = {z: _segs((800.0 + 0.02 * z, 700.0)) for z in (0, 100, 200, 300)}
        at[200] = (np.zeros((0, 2)), np.zeros((0, 2)))
        line, recs = axispolish.polish_line(guess, [0, 100, 200, 300], at.get, UM)
        want = [(0.0, 705.7870370370371, 800.0), (100.0, 705.7870370370371, 800.0),
                (300.0, 705.7870370370371, 805.7870370370371)]
        for a, b in zip(line, want):
            for u, v in zip(a, b):
                self.assertAlmostEqual(u, v, places=6)
        self.assertEqual([r.get("skipped") for r in recs], [None, None, True, None])

    def test_coverage_equals_windcheck_with_and_without_numba(self):
        segs = _segs((800.0, 700.0))
        pts = axispolish.disc((800.0, 700.0), 120.0, 11.0)
        ref = np.array([windcheck.coverage(segs, p) for p in pts])
        self.assertLess(np.abs(axispolish.coverage_many(segs, pts, use_numba=False) - ref).max(), 1e-9)
        self.assertLess(np.abs(axispolish.coverage_many(segs, pts) - ref).max(), 1e-9)
        empty = (np.zeros((0, 2)), np.zeros((0, 2)))
        self.assertEqual(axispolish.coverage_many(empty, [(1, 2)]).tolist(), [0.0])


class TestPieces(unittest.TestCase):
    def test_heights(self):
        guess = [(37.0, 0, 0), (420.0, 0, 0)]
        self.assertEqual(axispolish.heights(guess, 100), [100, 200, 300, 400])
        self.assertEqual(axispolish.heights(guess, 100, [0, 300]), [100, 200, 300])

    def test_centre_at_and_robust_axis(self):
        pts = [(0.0, 10.0, 20.0), (100.0, 30.0, 40.0)]
        self.assertEqual(axispolish.centre_at(pts, 50), (30.0, 20.0))
        self.assertEqual(axispolish.centre_at(pts, -5), (20.0, 10.0))
        line = [(float(z), 100.0 + 0.1 * z, 200.0) for z in range(0, 1000, 100)]
        line[4] = (400.0, 300.0, 200.0)                        # one point 160 voxels off
        kept, dropped = axispolish.robust_axis(line)
        self.assertEqual([d["z"] for d in dropped], [400.0])
        self.assertEqual(len(kept), 9)

    @unittest.skipIf(np is None, "needs numpy")
    def test_grid_round_trip_and_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.grid"
            axispolish.write_grid(f, [[(10, 10), (20, 15), (30, 30)], [(5, 5)]], (0, 0, 100, 100))
            head, lines = axispolish.read_grid(f)
            self.assertEqual(head["paths"], 1)
            self.assertEqual(lines[0].tolist(), [[10, 10], [20, 15], [30, 30]])
            self.assertEqual(axispolish.read_grid(b""), (None, []))
            with self.assertRaises(axispolish.PolishError):
                axispolish.read_grid(b"\0" * 60)
            (Path(d) / "xy").mkdir()
            (Path(d) / "xy" / "000100.grid").write_bytes(b"junk")
            segs_at = axispolish.grid_source(d)
            self.assertIsNone(segs_at(100))                   # unreadable
            self.assertIsNone(segs_at(200))                   # missing

    def test_bad_lines_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            for text in ("not json", '{"control_points": [{"x": 1, "y": 2, "z": 3}]}',
                         '{"control_points": [{"x": 1, "y": 2}]}', '{"control_points": [{"x": NaN, "y": 1, "z": 0},'
                         ' {"x": 1, "y": 1, "z": 9}]}'):
                p = Path(d) / "l.json"
                p.write_text(text)
                with self.subTest(text=text), self.assertRaises(axispolish.PolishError):
                    axispolish.load_line(p)

    def test_find_grids_picks_the_level0_grids_of_the_line_s_scan(self):
        prefix = "PHercT/representations/predictions/surfaces/"
        listing = [prefix + "20250101000000-surface-1-surface-m7-L0-th0.2.normal-grids/",
                   prefix + "20250101000000-surface-1-surface-m7-L0-th0.2.zarr/",
                   prefix + "20260101000000-surface-1-surface-m7-L2-th0.2.normal-grids/"]
        with mock.patch("kit.find.list_prefix", return_value=(listing, [])):
            self.assertEqual(axispolish.find_grids("PHercT", "20250101000000-8.640um.zarr"),
                             axispolish.BUCKET + "/" + listing[0].rstrip("/"))
            self.assertIsNone(axispolish.find_grids("PHercT", "20260101000000-2.4um.zarr"))


@unittest.skipIf(np is None, "needs numpy")
class TestTheCommand(unittest.TestCase):
    def test_an_offset_line_moves_back_into_the_spiral(self):
        with tempfile.TemporaryDirectory() as d:
            grids = _spiral_grids(Path(d) / "grids", {z: (800.0, 760.0) for z in range(0, 400, 100)}, turns=16)
            # 3.5 mm out, past the spiral's hollow core where coverage is flat
            line = _line(Path(d) / "line.json", [(0.0, 760.0, 800.0 + 3.5 * MM), (300.0, 760.0, 800.0 + 3.5 * MM)],
                         z_valid=[0, 300])
            out = Path(d) / "out" / "polished.json"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = axispolish.main([str(line), "--grids", str(grids), "--out", str(out), "--json"])
            self.assertEqual(rc, 0)
            summary = json.loads(buf.getvalue())
            self.assertEqual((summary["slices"], summary["polished"]), (4, 4))
            self.assertGreater(summary["median_gain_wraps"], 0)
            doc = json.loads(out.read_text())
            pts = sorted((p["z"], p["y"], p["x"]) for p in doc["control_points"])
            x, y = axispolish.centre_at(pts, 200)
            self.assertLess(math.hypot(x - 800.0, y - 760.0), 0.5 * MM)
            meta = doc["metadata"]
            self.assertEqual(meta["polish"]["rule"], axispolish.RULE)
            self.assertEqual(meta["polish"]["frozen_rule_sha256"][:8], "71d431b3")
            self.assertIn("Model output", meta["polish"]["label"])
            self.assertEqual(meta["total_points"], len(pts))
            self.assertEqual(meta["volume"], "20250101000000-8.640um-test.zarr")

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "empty"
            (empty / "xy").mkdir(parents=True)
            line = _line(Path(d) / "line.json", [(0.0, 760.0, 800.0), (300.0, 760.0, 800.0)])
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(axispolish.main([str(line), "--grids", str(empty), "--out", str(Path(d) / "o.json")]),
                                 2)
                self.assertEqual(axispolish.main([str(line), "--out", str(Path(d) / "o.json")]), 2)
                self.assertEqual(axispolish.main([str(line), "--grids", str(empty), "--every", "0",
                                                  "--out", str(Path(d) / "o.json")]), 2)
            self.assertIn("fewer than 2 of 4 slices", err.getvalue())
            self.assertIn("give --grids", err.getvalue())
            self.assertFalse((Path(d) / "o.json").exists())


if __name__ == "__main__":
    unittest.main()
