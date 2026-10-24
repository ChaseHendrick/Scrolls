"""Tests for kit/sheetgap.py on synthetic sheets: no network, no scroll data."""

import unittest

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

from kit import sheetgap as sg

RULE = dict(sg.GAP_RULE, max_thick_vox=6, threshold=1)


class ArrayReader:
    """A chunked reader over an in-memory volume (zyx); keys in `missing` read as None."""

    def __init__(self, vol, chunk=32, missing=()):
        self.vol, self.chunks = vol, (chunk,) * 3
        self.meta = {"shape": list(vol.shape)}
        self.missing = set(missing)

    def read(self, key):
        if tuple(key) in self.missing:
            return None
        c = self.chunks[0]
        z, y, x = (int(k) * c for k in key)
        out = np.zeros(self.chunks, np.uint8)
        part = self.vol[z:z + c, y:y + c, x:x + c]
        out[:part.shape[0], :part.shape[1], :part.shape[2]] = part
        return out


SHAPE = (112, 48, 128)          # z, y, x
ZA = 49.5                       # sheet A, 4 voxels thick


def zb_touch(x):
    """Sheet B: 14 voxels above A, pressed onto A (run 48..55, 8 thick) for x in 44..84."""
    x = np.asarray(x, float)
    return np.interp(x, [0, 32, 44, 84, 96, 200], [63.5, 63.5, 53.5, 53.5, 63.5, 63.5])


def paint(vol, zc, xs=None):
    """Mark a 4-voxel run centered at zc(x) for every y."""
    for x in range(SHAPE[2]) if xs is None else xs:
        c = float(zc(x))
        vol[int(round(c - 1.5)):int(round(c + 1.5)) + 1, :, x] = 1


def volume(sheet_b=zb_touch):
    v = np.zeros(SHAPE, np.uint8)
    paint(v, lambda x: ZA)
    paint(v, sheet_b)
    return v


def mesh(zc, step=4):
    xs = np.arange(8, 121, step, dtype=float)
    ys = np.arange(8, 41, step, dtype=float)
    X, Y = np.meshgrid(xs, ys)
    Z = np.vectorize(lambda x: float(zc(x)))(X)
    return np.stack([X, Y, Z], -1), np.ones(X.shape, bool)


def hop(x):
    """A trace on A that slides through the pressed zone and leaves on B."""
    if x < 44:
        return ZA
    if x <= 84:
        return ZA + (x - 44) / 40.0 * 4.0
    return float(zb_touch(x))


@unittest.skipIf(np is None, "needs numpy and scipy")
class RunsTest(unittest.TestCase):
    def prof(self, s):
        return np.array([[c == "#" for c in s]])

    def test_isolated_run(self):
        found, a, b, lo, hi = sg.runs(self.prof("....##.#.##...#...."), 2)
        # center index 9 is "#" in "##" at 9..10
        self.assertTrue(found[0])
        self.assertEqual((a[0], b[0], lo[0], hi[0]), (9, 10, 1, 3))

    def test_nearest_within_reach(self):
        found, a, b, _, _ = sg.runs(self.prof("..........#........"), 2)
        self.assertTrue(found[0])
        self.assertEqual((a[0], b[0]), (10, 10))
        found, *_ = sg.runs(self.prof("............#......"), 2)
        self.assertFalse(found[0])

    def test_classify(self):
        B = np.array([[c == "#" for c in s] for s in (
            "......####.........",   # ok: gaps 6 and 9
            "....#.####.........",   # gap of 1 below
            "..########.........",   # thick 8
            "...................",   # off
            "#########..........",   # touches the end
        )])
        st, centre, thick = sg.classify(B, np.zeros(len(B), bool), RULE)
        self.assertEqual(list(st), [sg.OK, sg.GAP, sg.THICK, sg.OFF, sg.THICK])
        self.assertEqual(thick[0], 4)
        self.assertAlmostEqual(centre[0], -1.5)


@unittest.skipIf(np is None, "needs numpy and scipy")
class SquareAndHolesTest(unittest.TestCase):
    def test_largest_square_matches_brute_force(self):
        rng = np.random.default_rng(0)
        for _ in range(20):
            m = rng.random((17, 23)) < 0.8
            s, r, c = sg.largest_square(m)
            brute = max([k for k in range(1, 18) for i in range(18 - k) for j in range(24 - k)
                         if i + k <= 17 and j + k <= 23 and m[i:i + k, j:j + k].all()] or [0])
            self.assertEqual(s, brute)
            if s:
                self.assertTrue(m[r:r + s, c:c + s].all())

    def test_small_enclosed_hole_joins(self):
        H = W = 30
        ok = np.ones((H, W), bool)
        status = np.zeros((H, W), np.int8)
        status[10:13, 10:13] = sg.GAP          # 9 cells at step 2: 36 vox2, under 400
        status[:, 25] = sg.THICK               # a wall: two components
        xyz = np.zeros((H, W, 3))
        xyz[..., 0], xyz[..., 1] = np.meshgrid(np.arange(W) * 2.0, np.arange(H) * 2.0)
        nrm = np.zeros((H, W, 3))
        nrm[..., 2] = 1
        cert = sg.Cert(status, np.zeros((H, W)), np.zeros((H, W)), xyz, nrm, ok, 2.0)
        lab = sg.components(cert, RULE)
        self.assertTrue((lab[10:13, 10:13] == lab[0, 0]).all())
        self.assertNotEqual(lab[0, 0], lab[0, 27])
        self.assertTrue((lab[:, 25] == -1).all())
        side, r, c, k = sg.best_square(lab)
        self.assertEqual(side, 25)


@unittest.skipIf(np is None, "needs numpy and scipy")
class SheetsTest(unittest.TestCase):
    def field(self, vol=None, missing=()):
        return sg.Field(ArrayReader(volume() if vol is None else vol, missing=missing), 1)

    def arms(self, xyz, valid, field, rule=RULE):
        cert = sg.check(xyz, valid, field, rule)
        X = cert.xyz[..., 0]
        lab = sg.components(cert, rule)
        seated = sg.components(cert, rule, mask=np.isin(cert.status, (sg.OK, sg.GAP, sg.THICK)), linked=False)

        def joined(L):
            a = L[(X < 40) & cert.ok]
            b = L[(X > 100) & cert.ok]
            return bool(set(a[a >= 0]) & set(b[b >= 0]))
        return cert, X, lab, joined(lab), joined(seated)

    def test_clean_trace_passes_apart_and_stops_at_contact(self):
        xyz, valid = mesh(lambda x: ZA)
        cert, X, lab, _, _ = self.arms(xyz, valid, self.field())
        self.assertAlmostEqual(cert.step, 2.0, places=6)
        self.assertTrue((cert.status[(X < 38) & cert.ok] == sg.OK).all())
        self.assertTrue((cert.status[(X > 50) & (X < 80) & cert.ok] == sg.THICK).all())
        self.assertGreater(lab.max(), 0)       # split into the two apart sides

    def test_hop_through_pressed_zone_is_not_joined(self):
        xyz, valid = mesh(hop)
        _, _, _, gap_joined, seated_joined = self.arms(xyz, valid, self.field())
        self.assertFalse(gap_joined)
        self.assertTrue(seated_joined)          # the per-point on-sheet test lets the hop through

    def test_blind_spot_single_run_switch(self):
        # The prediction itself draws one thin run from A up to B through the zone and drops the other halves:
        # the check cannot see this hop, so it must join (a check that cannot fail is no check).
        v = np.zeros(SHAPE, np.uint8)
        paint(v, lambda x: ZA, xs=range(0, 44))
        paint(v, lambda x: 63.5, xs=range(0, 44))
        paint(v, lambda x: ZA + (x - 44) / 40.0 * 14.0, xs=range(44, 85))
        paint(v, lambda x: ZA, xs=range(85, SHAPE[2]))
        paint(v, lambda x: 63.5, xs=range(85, SHAPE[2]))
        xyz, valid = mesh(lambda x: ZA if x < 44 else (ZA + (min(x, 84) - 44) / 40.0 * 14.0))
        _, _, _, gap_joined, _ = self.arms(xyz, valid, sg.Field(ArrayReader(v), 1))
        self.assertTrue(gap_joined)

    def test_missing_chunk(self):
        xyz, valid = mesh(lambda x: ZA)
        cert = sg.check(xyz, valid, self.field(missing={(1, 0, 0)}), RULE)
        X, Y = cert.xyz[..., 0], cert.xyz[..., 1]
        self.assertTrue((cert.status[(X < 30) & (Y < 30) & cert.ok] == sg.MISSING).all())
        self.assertTrue((cert.status[(X > 100) & cert.ok] == sg.OK).all())

    def test_plant_band_and_ramp(self):
        from kit import sheetrefs
        xb, vb = mesh(lambda x: float(zb_touch(x)))
        refB = sheetrefs.Ref("B", 2, xb, vb)
        xa, va = mesh(lambda x: ZA)
        up, _, nrm, ok, step = sg.densify(xa, va, 2.0)
        field = self.field()
        for mode in ("band", "ramp"):
            out = sg.plant(up, ok, refB, mode=mode, contact_vox=4.5, min_part_vox2=400, step=step)
            self.assertIsNotNone(out, mode)
            P, valid, w, s = out
            self.assertTrue(((w == 0) & valid).any() and ((w == 1) & valid).any())
            pnrm, _, pok, pstep = sheetrefs.grid_geometry(P, valid)
            cert = sg.check_dense(P, pnrm, pok, pstep, field, RULE)
            none = sg.components(cert, RULE, mask=pok, linked=False)
            self.assertTrue(sg.bridges(none, w, s, valid)[0], mode)      # the plant is a hop
            lab = sg.components(cert, RULE)
            self.assertFalse(sg.bridges(lab, w, s, valid)[0], mode)
        # band plants stay within the contact zone where they leave A, so they never cross the gap
        P, valid, w, s = sg.plant(up, ok, refB, mode="band", contact_vox=4.5, min_part_vox2=400, step=step)
        mid = valid & (w > 0) & (w < 1)
        self.assertTrue((np.abs(s[mid]) <= 4.5).all())


@unittest.skipIf(np is None, "needs numpy and scipy")
class HopbenchTest(unittest.TestCase):
    """The benchmark's bookkeeping on synthetic runs: calibration, reclassification and the tallies."""

    def test_recalc_matches_classify(self):
        from kit import hopbench as hb
        B = np.array([[c == "#" for c in s] for s in (
            "......####.........", "....#.####.........", "..########.........", "...................",
            "#########..........")])
        ok = np.ones((1, len(B)), bool)
        cert = sg.Cert(None, None, None, np.zeros((1, len(B), 3)), np.zeros((1, len(B), 3)), ok, 2.0)
        found, a, b, glo, ghi = sg.runs(B, RULE["on_run_vox"])
        hb._recalc(cert, (found, a, b, glo, ghi, np.zeros(len(B), bool), B.shape[1]), RULE)
        st, centre, _ = sg.classify(B, np.zeros(len(B), bool), RULE)
        self.assertEqual(list(cert.status[0]), list(st))
        np.testing.assert_allclose(cert.centre[0], centre)

    def test_calibrate_uses_isolated_runs_away_from_contact(self):
        from kit import hopbench as hb
        B = np.array([[c == "#" for c in s] for s in (
            "......####.........",      # 4 thick, both gaps: counted
            ".....######........",      # 6 thick, both gaps: counted
            "....#.####.........",      # gap of 1 below: not counted
            "......########.....")])    # 8 thick but in true contact: not counted
        ok = np.ones((1, len(B)), bool)
        cert = sg.Cert(None, None, None, None, None, ok, 2.0)
        found, a, b, glo, ghi = sg.runs(B, 2)
        truth_free = np.array([[True, True, True, False]])
        cal = hb.calibrate([("w", [0, 0], cert, (found, a, b, glo, ghi, np.zeros(4, bool), B.shape[1]),
                             truth_free)], RULE)
        self.assertEqual(cal["points"], 2)
        self.assertEqual(cal["hist"], {4: 1, 6: 1})
        self.assertEqual(cal["max_thick_vox"], 6)

    def test_tally_and_wilson(self):
        from kit import hopbench as hb
        rows = [{"status": "counted", "mode": m, "joined": {"none": True, "seated": True, "gap": g}}
                for m, g in (("band", False), ("band", True), ("ramp", False), ("ramp", False))]
        rows.append({"status": "no split", "mode": "band"})
        t = hb.tally(rows)
        self.assertEqual(t["all"]["n"], 4)
        self.assertEqual(t["all"]["gap"]["joined"], 1)
        self.assertEqual(t["band"]["gap"]["share"], 0.5)
        self.assertEqual(t["all"]["seated"]["share"], 1.0)
        self.assertEqual(t["not_counted"], 1)
        lo, hi = hb.wilson(1, 4)
        self.assertLess(lo, 0.25)
        self.assertGreater(hi, 0.25)
        self.assertEqual(hb.wilson(0, 0), [None, None])


@unittest.skipIf(np is None, "needs numpy and scipy")
class SheetrefsTest(unittest.TestCase):
    """Reference geometry on two synthetic flat sheets 10 voxels apart."""

    def test_match_offset_and_footprint(self):
        from kit import sheetrefs as sr
        X, Y = np.meshgrid(np.arange(0, 100, 5.0), np.arange(0, 60, 5.0))
        B = sr.Ref("B", 1, np.stack([X, Y, np.full(X.shape, 40.0)], -1), np.ones(X.shape, bool))
        P = np.array([[50.0, 30.0, 50.0], [50.0, 30.0, 30.0], [500.0, 30.0, 40.0]])
        s, ins, _, _ = sr.match(P, B)
        self.assertTrue(ins[0] and ins[1])
        self.assertFalse(ins[2])
        self.assertAlmostEqual(abs(s[0]), 10.0, places=6)
        self.assertAlmostEqual(s[0], -s[1], places=6)

    def test_download_retries_a_short_read(self):
        import http.client
        import io
        import tempfile
        from pathlib import Path
        from kit import sheetrefs as sr
        calls, waits = [], []

        def opener(req, timeout=60):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise http.client.IncompleteRead(b"x", 10)
            return io.BytesIO(b"chunk")

        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "a" / "0"
            self.assertTrue(sr._download("https://example.invalid/a/0", dest, opener, sleep=waits.append))
            self.assertEqual(dest.read_bytes(), b"chunk")
            self.assertEqual(len(calls), 3)
            self.assertEqual(waits, [2.0, 4.0])
            calls.clear()

            def broken(req, timeout=60):
                calls.append(1)
                raise ConnectionResetError("reset")

            with self.assertRaises(sr.BenchError):
                sr._download("https://example.invalid/a/1", Path(d) / "b", broken, tries=2, sleep=waits.append)
            self.assertEqual(len(calls), 2)
            self.assertFalse((Path(d) / "b").exists())

    def test_digest_is_stable(self):
        from kit import sheetrefs as sr
        self.assertEqual(sr.rule_digest(), sr.digest(sr.RULE))
        self.assertNotEqual(sr.rule_digest(dict(sr.RULE, version=3)), sr.rule_digest())
        self.assertEqual(sr.RULE["split"]["tune"][0], "w023")
        self.assertEqual(sr.RULE["split"]["tune"][-1], "w040")


if __name__ == "__main__":
    unittest.main()
