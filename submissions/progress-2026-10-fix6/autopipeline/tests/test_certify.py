"""kit meshqa certify (kit/certify.py): folds, crossings, rival adjudication, steep clusters, largest certified
square and the fiber score, on synthetic surfaces and volumes only."""

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
except ImportError:  # the core kit is standard library only
    np = None

if np is not None:
    from kit import certify as C
    from tests.test_meshqa import write_patch, write_zarr


def plane(h, w, step=2.0, origin=(100.0, 100.0, 100.0), u=(1, 0, 0), v=(0, 1, 0), shift=0.0):
    """Grid points origin + i*step*u + j*step*v + shift*normal."""
    u, v = np.asarray(u, float), np.asarray(v, float)
    u, v = u / np.linalg.norm(u), v / np.linalg.norm(v)
    n = np.cross(v, u)
    n /= np.linalg.norm(n)
    i, j = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    return (np.asarray(origin, float) + i[..., None] * step * u + j[..., None] * step * v + shift * n)


def sheet(P, name="s", valid=None):
    return C.Sheet(P, np.ones(P.shape[:2], bool) if valid is None else valid, name=name)


@unittest.skipIf(np is None, "needs numpy")
class Helpers(unittest.TestCase):
    def test_pairs_match_brute_force(self):
        rng = np.random.default_rng(3)
        A = rng.uniform(0, 50, (300, 3))
        B = rng.uniform(0, 50, (250, 3))
        a, b = C.pairs_within(A, B, 6.0, chunk=97)
        got = set(zip(a.tolist(), b.tolist()))
        d = np.linalg.norm(A[:, None] - B[None], axis=-1)
        want = set(zip(*[x.tolist() for x in np.nonzero(d <= 6.0)]))
        self.assertEqual(got, want)

    def test_largest_square_matches_brute_force(self):
        rng = np.random.default_rng(5)
        for _ in range(20):
            ok = rng.random((9, 11)) > 0.25
            side, i, j = C.largest_square(ok)
            best = 0
            for s in range(1, 10):
                if any(ok[r:r + s, c:c + s].all() for r in range(9 - s + 1) for c in range(11 - s + 1)):
                    best = s
            self.assertEqual(side, best)
            if side:
                self.assertTrue(ok[i:i + side, j:j + side].all())

    def test_largest_square_equals_the_cell_loop(self):
        def cell_loop(ok):
            """largest_square as it was: the DP one cell at a time, the first strictly larger square kept."""
            H, W = ok.shape
            best, at = 0, (None, None)
            prev = np.zeros(W + 1, np.int64)
            for i in range(H):
                cur = np.zeros(W + 1, np.int64)
                for j in np.flatnonzero(ok[i]):
                    v = 1 + min(prev[j], prev[j + 1], cur[j])
                    cur[j + 1] = v
                    if v > best:
                        best, at = int(v), (int(i - v + 1), int(j - v + 1))
                prev = cur
            return best, at[0], at[1]

        rng = np.random.default_rng(11)
        grids = [np.zeros((0, 4), bool), np.zeros((5, 0), bool), np.zeros((0, 0), bool), np.ones((1, 1), bool),
                 np.zeros((1, 1), bool), np.ones((6, 9), bool), np.zeros((4, 3), bool), np.ones((1, 7), bool),
                 np.eye(5, dtype=bool), np.tile([[1, 1, 0], [1, 1, 0], [0, 0, 0]], (3, 3)).astype(bool)]
        for _ in range(600):
            grids.append(rng.random(tuple(rng.integers(1, 14, 2))) < rng.uniform(0.3, 0.95))
        for ok in grids:
            got = C.largest_square(ok)
            self.assertEqual(got, cell_loop(ok), ok.astype(int).tolist())
            self.assertTrue(all(v is None or type(v) is int for v in got))
        ints = (rng.random((8, 8)) < 0.8).astype(np.uint8) * 3        # truthy cells, not bool
        self.assertEqual(C.largest_square(ints), cell_loop(ints))

    def test_label4_and_dilate(self):
        m = np.zeros((5, 5), bool)
        m[0, 0] = m[0, 1] = m[4, 4] = True
        m[1, 1] = True            # touches (0, 1): one component of three
        lab, sizes = C.label4(m)
        self.assertEqual(sorted(sizes.tolist()), [1, 3])
        self.assertEqual(C.dilate4(np.eye(1, dtype=bool), 2).sum(), 1)
        d = np.zeros((5, 5), bool); d[2, 2] = True
        self.assertEqual(C.dilate4(d, 2).sum(), 13)

    def test_normals_and_steps(self):
        s = sheet(plane(10, 12, step=3.0))
        self.assertAlmostEqual(s.step_i, 3.0)
        self.assertAlmostEqual(s.step_j, 3.0)
        self.assertTrue(s.nvalid.all())
        self.assertTrue(np.allclose(np.abs(s.N[..., 2]), 1.0))


@unittest.skipIf(np is None, "needs numpy")
class Geometry(unittest.TestCase):
    P = 15.0

    def test_flat_sheet_is_certified_whole(self):
        s = sheet(plane(40, 40))
        rep, fail = C.certify(s, self.P, voxel_um=10.0)
        self.assertEqual(rep["fold"]["cells"], 0)
        self.assertEqual(rep["certified_square"]["cells"], 40)
        self.assertAlmostEqual(rep["certified_square"]["mm"], 40 * 2.0 * 10.0 / 1000.0)
        self.assertFalse(fail.any())

    def test_holes_fail_and_shrink_the_square(self):
        valid = np.ones((30, 30), bool)
        valid[15, 15] = False
        rep, fail = C.certify(sheet(plane(30, 30), valid=valid), self.P)
        self.assertEqual(rep["counts"]["hole"], 1)
        self.assertEqual(rep["certified_square"]["cells"], 15)

    def test_hairpin_fold_is_flagged(self):
        # rows 0..39 on the plane, rows 40..79 back over it one pitch away: a sheet folded onto the next winding
        bottom = plane(40, 40, step=4.0)
        top = plane(40, 40, step=4.0, shift=self.P)[::-1]
        s = sheet(np.concatenate([bottom, top], 0))
        rep, fail = C.certify(s, self.P)
        self.assertTrue(rep["fold"]["folds"])
        self.assertGreater(rep["fold"]["cells"], 0.5 * 80 * 40)
        self.assertEqual(rep["fold"]["hairpin_cells"], rep["fold"]["cells"])
        self.assertEqual(rep["fold"]["wrap_cells"], 0)
        self.assertLess(rep["certified_square"]["cells"], 40)

    def spiral(self, turns=1.5, rows=40, step=4.0, r0=60.0):
        """A winding of an Archimedean spiral (radius grows one pitch a turn) traced past one full turn."""
        th = np.arange(0.0, 2 * math.pi * turns, step / (r0 + self.P))
        r = r0 + self.P * th / (2 * math.pi)
        z = np.arange(rows) * step
        Z, T = np.meshgrid(z, th, indexing="ij")
        R = np.broadcast_to(r, T.shape)
        return np.stack([200 + R * np.cos(T), 200 + R * np.sin(T), 100 + Z], -1)

    def test_winding_past_one_turn_is_reported_not_failed(self):
        s = sheet(self.spiral())
        rep, fail = C.certify(s, self.P)
        f = rep["fold"]
        self.assertEqual(f["rule"], "hairpin")
        self.assertEqual(f["hairpin_cells"], 0)
        self.assertGreater(f["wrap_area_vox2"], C.FOLD_MIN_AREA)
        self.assertFalse(f["folds"])
        self.assertEqual(rep["counts"]["fold"], 0)
        self.assertFalse(fail.any())

    def test_fold_rule_any_fails_the_wrap_as_the_source_does(self):
        s = sheet(self.spiral())
        rep, fail = C.certify(s, self.P, fold_rule="any")
        self.assertTrue(rep["fold"]["folds"])
        self.assertEqual(rep["counts"]["fold"], rep["fold"]["wrap_cells"])
        self.assertGreater(rep["counts"]["fold"], 0)
        with self.assertRaises(C.CertifyError):
            C.certify(s, self.P, fold_rule="maybe")

    def test_one_turn_or_less_has_no_wrap(self):
        rep, _ = C.certify(sheet(self.spiral(turns=0.9)), self.P, fold_rule="any")
        self.assertEqual(rep["fold"]["cells"], 0)

    def test_small_fold_under_area_threshold_does_not_fail(self):
        bottom = plane(12, 12, step=4.0)
        top = plane(12, 12, step=4.0, shift=self.P)[::-1]
        s = sheet(np.concatenate([bottom, top], 0))
        rep, _ = C.certify(s, self.P)
        self.assertGreater(rep["fold"]["cells"], 0)
        self.assertFalse(rep["fold"]["folds"])        # at most 288 cells x 16 vox2 < 16384
        self.assertEqual(rep["counts"]["fold"], 0)

    def test_parallel_and_coincident_neighbours_are_not_crossings(self):
        a = sheet(plane(30, 30), "a")
        nxt = sheet(plane(30, 30, shift=self.P), "next winding")
        same = sheet(plane(30, 30, origin=(101.0, 101.0, 100.3)), "same sheet")
        rep, _ = C.certify(a, self.P, compare=[nxt, same])
        self.assertEqual([c["cells"] for c in rep["crossings"]], [0, 0])
        self.assertEqual(rep["certified_square"]["cells"], 30)

    def test_transverse_sheet_is_a_crossing(self):
        a = sheet(plane(40, 40), "a")
        # a vertical sheet through x = 140 (row 20 of a), spanning z 80..120
        cross = sheet(plane(20, 40, origin=(140.0, 100.0, 80.0), u=(0, 0, 1), v=(0, 1, 0)), "crosser")
        rep, fail = C.certify(a, self.P, compare=[cross])
        c = rep["crossings"][0]["cells"]
        self.assertGreater(c, 0)
        rows = np.nonzero((fail & C.FAIL_CROSS).any(1))[0]
        self.assertTrue(set(rows.tolist()) <= set(range(17, 24)), rows)
        self.assertLess(rep["certified_square"]["cells"], 40)

    def test_rival_adjudication(self):
        a = sheet(plane(40, 40), "a")
        rival = sheet(plane(20, 40, origin=(140.0, 100.0, 80.0), u=(0, 0, 1), v=(0, 1, 0)), "rival")
        ref_a = sheet(plane(40, 40, origin=(100.5, 100.5, 100.5)), "ref on a")
        ref_rival = sheet(plane(20, 40, origin=(140.5, 100.5, 80.0), u=(0, 0, 1), v=(0, 1, 0)), "ref on rival")
        rep, _ = C.certify(a, self.P, compare=[], rivals=[rival])
        self.assertTrue(rep["rivals"][0]["lost"])                     # nothing to adjudicate with: strict
        # compare surfaces that agree with a, placed away from the crossing so they do not cross a themselves
        rep, fail = C.certify(a, self.P, rivals=[rival], compare=[ref_a])
        self.assertFalse(rep["rivals"][0]["lost"])
        self.assertEqual(rep["counts"]["rival"], 0)
        rep, _ = C.certify(a, self.P, rivals=[rival], compare=[ref_rival])
        self.assertTrue(rep["rivals"][0]["lost"])


@unittest.skipIf(np is None, "needs numpy")
class Volumes(unittest.TestCase):
    def test_steep_against_prediction(self):
        # prediction: a slab z in [118, 122) over the whole box
        vol = np.zeros((240, 240, 240), np.uint8)
        vol[118:122] = 255
        pred = C.ArrayVolume(vol)
        flat = sheet(plane(40, 40, step=2.0, origin=(60.0, 60.0, 120.0)), "flat")
        st, rec = C.steep_cells(flat, pred)
        self.assertEqual(rec["flagged"], 0)
        self.assertEqual(rec["measurable"], 1600)
        # a sheet tilted 45 degrees about y crossing the slab: points near the slab are steep
        tilt = sheet(plane(40, 40, step=2.0, origin=(60.0, 60.0, 100.0), u=(1, 0, 1), v=(0, 1, 0)), "tilt")
        st, rec = C.steep_cells(tilt, pred, s_min=10)
        self.assertGreater(rec["flagged"], 0)
        self.assertEqual(rec["flagged"], rec["measurable"])
        self.assertTrue(st.any())
        st, rec = C.steep_cells(tilt, pred, s_min=10 ** 6)
        self.assertFalse(st.any())                                     # a cluster under S does not fail

    def test_fibre_score_separates_stripes_from_noise(self):
        voxel_um = 10.0                                                # 0.3 mm period = 30 voxels
        rng = np.random.default_rng(0)
        z = np.arange(64)[:, None, None]
        y = np.arange(400)[None, :, None]
        x = np.arange(400)[None, None, :]
        stripes = 1000 + 300 * np.sin(2 * np.pi * x / 30.0) + 300 * np.sin(2 * np.pi * y / 30.0) + \
            rng.normal(0, 30, (64, 400, 400))
        noise = 1000 + rng.normal(0, 300, (64, 400, 400))
        s = sheet(plane(150, 150, step=2.0, origin=(20.0, 20.0, 32.0)), "flat")
        a = C.fibre_score(s, C.ArrayVolume(stripes.astype(np.float32)), voxel_um, fine_step=1.0, nw=8)
        b = C.fibre_score(s, C.ArrayVolume(noise.astype(np.float32)), voxel_um, fine_step=1.0, nw=8)
        self.assertEqual(a["windows"], 8)
        self.assertGreater(a["score"], 0.5)
        self.assertLess(abs(b["score"] - b["white_noise_share"]), 0.03)
        self.assertGreater(a["score"], 5 * b["score"])

    def test_fibre_skips_masked_scan(self):
        vol = np.zeros((64, 400, 400), np.float32)                     # all masked: zero everywhere
        s = sheet(plane(150, 150, step=2.0, origin=(20.0, 20.0, 32.0)))
        r = C.fibre_score(s, C.ArrayVolume(vol), 10.0, fine_step=1.0, nw=4, maxdraw=50)
        self.assertEqual(r["windows"], 0)
        self.assertIsNone(r["score"])

    def test_chunkwise_sampling_matches_the_array(self):
        rng = np.random.default_rng(7)
        arr = rng.integers(1, 255, (70, 90, 100), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            vol = C.open_volume(str(write_zarr(Path(tmp) / "ct.zarr", arr, chunk=32)))
            pts = np.stack([rng.integers(-5, 105, 500), rng.integers(-5, 95, 500), rng.integers(-5, 75, 500)], 1)
            got = C.sample_nearest(vol, pts.reshape(20, 25, 3))
            x, y, z = pts.T
            inside = (x >= 0) & (x < 100) & (y >= 0) & (y < 90) & (z >= 0) & (z < 70)
            want = np.zeros(500)
            want[inside] = arr[z[inside], y[inside], x[inside]]
            self.assertEqual(got.shape, (20, 25))
            self.assertTrue(np.array_equal(got.reshape(-1), want))
            arrv = C.sample_nearest(C.ArrayVolume(arr), pts[inside])
            self.assertTrue(np.array_equal(arrv, want[inside]))

    def test_bands_white_noise_share(self):
        band, nondc, white = C.fibre_bands(0.0079)
        self.assertGreater(band.sum(), 0)
        self.assertAlmostEqual(white, band.sum() / nondc.sum())
        # the default step reproduces the source's white-noise figure, 0.0293
        self.assertAlmostEqual(C.fibre_bands(C.FIBRE_STEP_MM)[2], 0.0293, places=4)


@unittest.skipIf(np is None, "needs numpy")
class CommandLine(unittest.TestCase):
    def test_cli_on_tifxyz_and_npy(self):
        with tempfile.TemporaryDirectory() as tmp:
            P = plane(40, 40, step=2.0, origin=(60.0, 60.0, 120.0))
            d = write_patch(Path(tmp) / "surf", P[..., 0], P[..., 1], P[..., 2])
            vol = np.zeros((240, 240, 240), np.uint8)
            vol[118:122] = 255
            np.save(Path(tmp) / "pred.npy", vol)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["meshqa", "certify", str(d), "--pitch", "15", "--voxel-um", "7.91",
                                 "--prediction", str(Path(tmp) / "pred.npy"), "--json", "--fold-rule", "any",
                                 "--fail-map", str(Path(tmp) / "fail.tif")])
            self.assertEqual(code, 0, err.getvalue())
            rep = json.loads(out.getvalue())
            self.assertEqual(rep["fold"]["rule"], "any")
            self.assertEqual(rep["certified_square"]["cells"], 40)
            self.assertEqual(rep["steep"]["flagged"], 0)
            self.assertFalse(rep["certified_square"]["reaches"])       # 40 x 2 voxels x 7.91 um is 0.63 mm
            self.assertTrue((Path(tmp) / "fail.tif").is_file())

    def test_cli_needs_pitch(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(["meshqa", "certify", "x"])


if __name__ == "__main__":
    unittest.main()
