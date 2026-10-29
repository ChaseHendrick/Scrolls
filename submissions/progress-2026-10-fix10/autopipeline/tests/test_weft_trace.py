"""Weft (scripts/afvfibers/weft_trace.py), our own fiber tracer, on synthetic probability volumes with known fibers:
a straight and a curved fiber, an H/V crossing where the model gives the crossing to H, a gap with no probability
that must be bridged, and a staggered parallel neighbor that must not be merged. Also the AFV writer (villa's
structural rules), the coordinate convention, exterior trimming and box reads, and the data paths end to end through
synthetic block files (crop, v2crop, stats, block loading across faces). Skipped without numpy and scipy (and
numcodecs for the block files)."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "afvfibers"))

try:
    import numpy as np
    from scipy.spatial import cKDTree
    import weft_trace as w
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False


def tube(shape, curves, radius=2.2):
    """uint8 probability: 255 within `radius` of any curve, falling to 0 over 1.5 more voxels."""
    zz, yy, xx = np.indices(shape)
    P = np.stack([zz.ravel(), yy.ravel(), xx.ravel()], 1).astype(float)
    out = np.zeros(len(P))
    for c in curves:
        d, _ = cKDTree(c).query(P, distance_upper_bound=radius + 2)
        out = np.maximum(out, np.nan_to_num(np.clip((radius + 1.5 - d) / 1.5, 0, 1)))
    return (out.reshape(shape) * 255).astype(np.uint8)


def line(a, b, n=400):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) * np.array(a, float) + t * np.array(b, float)


def dist_to(curve, pts, ends=3):
    """Distances from the fiber's points to the true curve, leaving out `ends` points at each end (the probability
    tube runs about its radius past the curve's ends, and so does the traced fiber)."""
    return cKDTree(curve).query(pts[ends:len(pts) - ends])[0]


@unittest.skipUnless(HAVE, "numpy, scipy (and numba for speed) needed")
class TestTracing(unittest.TestCase):
    def trace(self, own, other=None):
        fibers, info = w.trace_family(own, np.zeros_like(own) if other is None else other)
        return fibers, info

    def test_straight(self):
        truth = line((2, 24, 24), (77, 24, 24))
        fibers, _ = self.trace(tube((80, 48, 48), [truth]))
        self.assertEqual(len(fibers), 1)
        p = fibers[0]["points"]
        self.assertLess(dist_to(truth, p).max(), 0.25)
        self.assertGreater(w.length(p), 72)
        self.assertGreater(fibers[0]["confidence"], 0.8)

    def test_curved(self):
        t = np.linspace(0, 1, 600)
        a = 0.2 + 2.6 * t
        truth = np.stack([np.full_like(t, 20.0), 48 + 30 * np.sin(a), 48 + 30 * np.cos(a)], 1)
        fibers, _ = self.trace(tube((40, 96, 96), [truth]))
        self.assertEqual(len(fibers), 1)
        p = fibers[0]["points"]
        self.assertLess(dist_to(truth, p).max(), 0.5)
        self.assertGreater(w.length(p), 0.9 * 30 * 2.6)

    def test_crossing_continues(self):
        v = line((2, 24, 32), (61, 24, 32))
        h = line((32, 24, 2), (32, 24, 61))
        V, H = tube((64, 48, 64), [v]), tube((64, 48, 64), [h])
        V[H > 128] = 0                        # the model gives the crossing to H
        fibers, info = self.trace(V, H)
        self.assertEqual(len(fibers), 1, info)
        p = fibers[0]["points"]
        self.assertLess(p[:, 0].min(), 5)
        self.assertGreater(p[:, 0].max(), 58)
        self.assertLess(dist_to(v, p).max(), 1.0)
        hf, _ = self.trace(H, V)
        self.assertEqual(len(hf), 1)

    def test_gap_bridged(self):
        truth = line((2, 20, 20), (77, 20, 20))
        V = tube((80, 40, 40), [truth])
        V[37:43] = 0                          # six voxels with no probability at all
        fibers, info = self.trace(V)
        self.assertEqual(len(fibers), 1, info)
        self.assertEqual(fibers[0]["parts"]["links"], 1)
        self.assertGreater(fibers[0]["parts"]["bridged_fraction"], 0)
        self.assertLess(dist_to(truth, fibers[0]["points"]).max(), 1.0)
        # a bridged fiber is less certain than an unbroken one
        whole, _ = self.trace(tube((80, 40, 40), [truth]))
        self.assertLess(fibers[0]["confidence"], whole[0]["confidence"])

    def test_parallel_neighbor_not_merged(self):
        a = line((2, 20, 18), (50, 20, 18))
        b = line((56, 20, 26), (87, 20, 26))  # starts 6 voxels later, 8 voxels to the side
        fibers, info = self.trace(tube((90, 40, 48), [a, b]))
        self.assertEqual(len(fibers), 2, info)
        for f in fibers:
            x = f["points"][:, 2]
            self.assertLess(x.max() - x.min(), 2.0)       # each stays in its own column

    def test_long_gap_refused(self):
        truth = line((2, 20, 20), (97, 20, 20))
        V = tube((100, 40, 40), [truth])
        V[40:70] = 0                          # 30 voxels: beyond link_radius
        fibers, _ = self.trace(V)
        self.assertEqual(len(fibers), 2)

    def test_closed_ring_stops(self):
        t = np.linspace(0, 2 * np.pi, 800)
        ring = np.stack([np.full_like(t, 16.0), 40 + 20 * np.sin(t), 40 + 20 * np.cos(t)], 1)
        fibers, info = self.trace(tube((32, 80, 80), [ring]))
        self.assertEqual(info["fragment_ends"]["limit"], 0, info)
        total = sum(w.length(f["points"]) for f in fibers)
        self.assertLess(total, 2 * np.pi * 20 * 1.1)       # once around, not round and round
        self.assertGreater(total, 2 * np.pi * 20 * 0.8)

    def test_empty(self):
        fibers, info = self.trace(np.zeros((32, 32, 32), np.uint8))
        self.assertEqual(fibers, [])
        self.assertEqual(info["seeds"], 0)

    def test_both_families(self):
        v = line((2, 16, 16), (45, 16, 16))
        h = line((24, 30, 2), (24, 30, 45))
        pooled = np.stack([tube((48, 48, 48), [v]), tube((48, 48, 48), [h])])
        out, infos = w.trace_volume(pooled)
        self.assertEqual(sorted(f for f, _ in out), ["H", "V"])
        self.assertEqual(set(infos), {"V", "H"})


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestPieces(unittest.TestCase):
    def test_hermite_ends(self):
        a, b = np.array([0.0, 0, 0]), np.array([10.0, 0, 0])
        t = np.array([1.0, 0, 0])
        br = w.hermite(a, t, b, t)
        self.assertEqual(len(br), 9)
        self.assertTrue(np.allclose(br[:, 1:], 0))
        self.assertTrue(np.all(np.diff(br[:, 0]) > 0))

    def test_coordinates(self):
        q = w.tgrid_to_l0(np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]]), [10, 20, 30], 2)
        # level coordinate = 2 t + 0.5 + origin, times 4, returned as XYZ
        self.assertTrue(np.allclose(q[0], [(30.5) * 4, (20.5) * 4, (10.5) * 4]))
        self.assertTrue(np.allclose(q[1], [(6.5 + 30) * 4, (4.5 + 20) * 4, (2.5 + 10) * 4]))

    def test_exterior_trim_keeps_inside(self):
        mask = np.zeros((4, 4, 4), bool)
        mask[:, :, 3] = True                  # cells with x >= 30 (cell 10) are outside
        p = np.stack([np.linspace(0, 39, 40), np.full(40, 5.0), np.full(40, 5.0)], 1)
        pieces = w.exterior_trim(p, mask, 10)
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0][-1, 0], 29)
        mask[:, :, 1] = True
        self.assertEqual(len(w.exterior_trim(p, mask, 10)), 2)

    def test_link_refuses_through_other_fiber(self):
        # two collinear fragments with a third fiber lying across the gap: no join
        f1 = line((0, 10, 10), (20, 10, 10), 21)
        f2 = line((28, 10, 10), (48, 10, 10), 21)
        f3 = line((24, 10, 0), (24, 10, 20), 21)
        S = np.full((50, 20, 20), 255.0)
        joins, _ = w.link([f1, f2, f3], S, S, dict(w.DEFAULTS))
        pairs = {tuple(sorted((j[0], j[2]))) for j in joins}
        self.assertNotIn((0, 1), pairs)
        joins, _ = w.link([f1, f2], S, S, dict(w.DEFAULTS))
        self.assertEqual(len(joins), 1)

    def test_link_refuses_third_fiber_just_off_the_bridge(self):
        # the third fiber passes 0.9 voxels from the bridge, with its points placed so that every second one (the
        # thinned set the guard used to read) is about 1.35 voxels away: the guard must still see it
        f1 = line((0, 10, 10), (20, 10, 10), 21)
        f2 = line((28, 10, 10), (48, 10, 10), 21)
        f3 = line((24, 10.9, -1), (24, 10.9, 21), 23)
        S = np.full((50, 20, 24), 255.0)
        joins, _ = w.link([f1, f2, f3], S, S, dict(w.DEFAULTS))
        self.assertNotIn((0, 1), {tuple(sorted((j[0], j[2]))) for j in joins})


try:
    import numcodecs
    HAVE_CODEC = HAVE
except ImportError:  # pragma: no cover
    HAVE_CODEC = False

LEVEL, BLOCK, SHAPE2 = 2, 64, (96, 96, 128)       # level-2 grid of 2 x 2 x 2 blocks of 64 (the last ones partial)


def native_tube(shape, axis, center, radius=4.0, ramp=3.0):
    """uint8 native probability of a straight tube along `axis` whose center line sits at the level coordinates
    `center` (the other two axes, in order). An integer level coordinate is a voxel's center."""
    idx = np.indices(shape).astype(float)
    others = [a for a in range(3) if a != axis]
    d = np.sqrt(sum((idx[a] - c) ** 2 for a, c in zip(others, center)))
    return (np.clip((radius + ramp - d) / ramp, 0, 1) * 255).astype(np.uint8)


def write_blocks(d, nat):
    """Native and 2x average-pooled block files in the published layout (blocks/native|pooled/Z_Y_X.blosc)."""
    codec = numcodecs.Blosc(cname="zstd", clevel=3, shuffle=numcodecs.Blosc.BITSHUFFLE)
    for sub in ("native", "pooled"):
        (Path(d) / sub).mkdir(parents=True, exist_ok=True)
    for z in range(0, SHAPE2[0], BLOCK):
        for y in range(0, SHAPE2[1], BLOCK):
            for x in range(0, SHAPE2[2], BLOCK):
                b = np.ascontiguousarray(nat[:, z:z + BLOCK, y:y + BLOCK, x:x + BLOCK])
                (Path(d) / "native" / f"{z}_{y}_{x}.blosc").write_bytes(codec.encode(b))
                c, dz, dy, dx = b.shape
                q = b[:, :dz // 2 * 2, :dy // 2 * 2, :dx // 2 * 2].astype(np.float32)
                q = q.reshape(c, dz // 2, 2, dy // 2, 2, dx // 2, 2).mean((2, 4, 6))
                pooled = np.ascontiguousarray(np.rint(q).astype(np.uint8))
                (Path(d) / "pooled" / f"{z}_{y}_{x}.blosc").write_bytes(codec.encode(pooled))


def write_volume(d):
    vol = {"scan": "TEST", "level": LEVEL, "voxel_um": 9.596, "shape_zyx": list(SHAPE2), "block": BLOCK,
           "coordinate_space": "TEST/0", "ct": "https://example.invalid/TEST/volumes/v.zarr/2"}
    out = Path(d) / "volume.json"
    out.write_text(json.dumps(vol))
    return out


def run_main(argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = w.main([str(v) for v in argv])
    return rc, buf.getvalue()


@unittest.skipUnless(HAVE_CODEC, "numpy, scipy and numcodecs needed")
class TestDataPaths(unittest.TestCase):
    """End to end through the block files: `crop` must put a tube back at its known L0 position (Qual's convention:
    pooled voxel t at level coordinate 2 t + 0.5, then L0 = 4 x level coordinate), across block faces."""

    def test_crop_puts_tube_at_its_l0_position(self):
        # V tube along x at level (z, y) = (41.3, 63.7): it crosses the x block face at 64 and sits on the y face
        # at 64; H tube along z at level (y, x) = (30.2, 70.6), across the z face
        nat = np.zeros((2,) + SHAPE2, np.uint8)
        nat[0] = native_tube(SHAPE2, 2, (41.3, 63.7))
        nat[1] = native_tube(SHAPE2, 0, (30.2, 70.6))
        with tempfile.TemporaryDirectory() as d:
            write_blocks(Path(d) / "blocks", nat)
            vol = write_volume(d)
            out = Path(d) / "weft.afv"
            crop = [8 * 4, 120 * 4, 8 * 4, 88 * 4, 8 * 4, 88 * 4]       # L0 x0 x1 y0 y1 z0 z1
            rc, _ = run_main(["crop", "--volume", vol, "--blocks", Path(d) / "blocks", "--crop-l0", *crop,
                              "--out", out])
            self.assertEqual(rc, 0)
            fib = w.read_afv(out)
            fams = sorted(f for _, f, _, _ in fib)
            self.assertEqual(fams, ["H", "V"])
            for _, fam, p, _ in fib:
                lo, hi = np.array(crop[0::2]), np.array(crop[1::2])
                self.assertTrue(((p >= lo - 1e-6) & (p <= hi + 1e-6)).all())
                mid = p[5:-5]
                if fam == "V":      # XYZ L0: y = 4 x 63.7, z = 4 x 41.3
                    self.assertGreater(np.ptp(p[:, 0]), 0.8 * (crop[1] - crop[0]))
                    self.assertLess(abs(np.median(mid[:, 1]) - 4 * 63.7), 1.0)
                    self.assertLess(abs(np.median(mid[:, 2]) - 4 * 41.3), 1.0)
                else:               # x = 4 x 70.6, y = 4 x 30.2
                    self.assertGreater(np.ptp(p[:, 2]), 0.8 * (crop[5] - crop[4]))
                    self.assertLess(abs(np.median(mid[:, 0]) - 4 * 70.6), 1.0)
                    self.assertLess(abs(np.median(mid[:, 1]) - 4 * 30.2), 1.0)

    def test_load_pooled_matches_pooling_across_faces(self):
        rng = np.random.default_rng(3)
        nat = rng.integers(0, 256, (2,) + SHAPE2).astype(np.uint8)
        with tempfile.TemporaryDirectory() as d:
            write_blocks(Path(d), nat)
            lo2, hi2 = np.array([40, 50, 60]), np.array([96, 96, 128])
            got = w.load_pooled(d, lo2, hi2, np.array(SHAPE2), block=BLOCK)
            q = nat[:, 40:96, 50:96, 60:128].astype(np.float32).reshape(2, 28, 2, 23, 2, 34, 2).mean((2, 4, 6))
            self.assertTrue(np.array_equal(got, np.rint(q).astype(np.uint8)))
            got = w.load_native(d, lo2, hi2, np.array(SHAPE2), block=BLOCK)
            self.assertTrue(np.array_equal(got, nat[:, 40:96, 50:96, 60:128]))

    def test_v2crop_clips_to_box(self):
        p = np.stack([np.linspace(0, 400, 401), np.full(401, 100.0), np.full(401, 100.0)], 1)
        q = np.stack([np.full(50, 900.0), np.linspace(0, 49, 50), np.full(50, 5.0)], 1)     # outside the box
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "v2.afv"
            w.write_afv([("V", p, None), ("H", q, None)], src, dict(TestAfv.FRAME), "AFV V2", {}, 2.399,
                        weft_table=False)
            out = Path(d) / "crop.afv"
            rc, _ = run_main(["v2crop", "--afv", src, "--crop-l0", 100, 300, 0, 200, 0, 200, "--out", out])
            self.assertEqual(rc, 0)
            got = w.read_afv(out)
            self.assertEqual(len(got), 1)
            self.assertAlmostEqual(got[0][2][0, 0], 100.0)
            self.assertAlmostEqual(got[0][2][-1, 0], 300.0)
            self.assertEqual(got[0][3]["v2_fiber_id"], 1)

    def test_stats_uses_nearest_native_voxel(self):
        # V probability 255 only in the plane of level z voxel 40; a V fiber at level z 39.6 lies nearest to that
        # voxel (rounding), while the floor would pick voxel 39 and miss it; --min-len-um leaves a short fiber out
        nat = np.zeros((2,) + SHAPE2, np.uint8)
        nat[0, 40] = 255
        on = np.stack([np.linspace(40, 400, 50), np.full(50, 200.0), np.full(50, 4 * 39.6)], 1)
        short = np.array([[100.0, 100, 4 * 39.6], [110.0, 100, 4 * 39.6]])
        with tempfile.TemporaryDirectory() as d:
            write_blocks(Path(d) / "blocks", nat)
            vol = write_volume(d)
            f = Path(d) / "a.afv"
            w.write_afv([("V", on, None), ("V", short, None)], f, dict(TestAfv.FRAME), "t", {}, 2.399)
            crop = [0, 512, 0, 384, 0, 384]
            rc, txt = run_main(["stats", "--afv", f, "--volume", vol, "--blocks", Path(d) / "blocks",
                                "--crop-l0", *crop])
            r = json.loads(txt)[str(f)]
            self.assertEqual(r["fibers"], 2)
            self.assertEqual(r["share_points_own_p_ge_0.5"], 1.0)
            rc, txt = run_main(["stats", "--afv", f, "--volume", vol, "--blocks", Path(d) / "blocks",
                                "--crop-l0", *crop, "--min-len-um", 50])
            self.assertEqual(json.loads(txt)[str(f)]["fibers"], 1)


@unittest.skipUnless(HAVE, "numpy and scipy needed")
class TestAfv(unittest.TestCase):
    FRAME = {"coordinate_base_shape_zyx": [400, 300, 300], "vc_open_data_source_coordinate_level": 0,
             "vc_open_data_source_coordinate_scale_factor": 1, "vc_open_data_source_original_resolution": 2.399,
             "vc_open_data_coordinate_space": "TEST/0"}

    def write(self, d, fibers, **kw):
        out = Path(d) / "t.afv"
        s = w.write_afv(fibers, out, dict(self.FRAME), "test", {"note": "unit test"}, 2.399, **kw)
        return out, s

    def test_villa_rules(self):
        long_ = np.stack([np.arange(600.0), np.full(600, 7.0), np.full(600, 9.0)], 1)
        short = np.array([[1.0, 2, 3], [4, 5, 6]])
        with tempfile.TemporaryDirectory() as d:
            out, s = self.write(d, [("V", long_, {"weft": {"confidence": 0.7}}), ("H", short, None)])
            self.assertEqual(s, {"fibers": 2, "points": 602, "blocks": 4})
            db = sqlite3.connect(str(out))
            self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], 0x56434643)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM metadata")}
            self.assertIs(meta["complete"], True)
            self.assertEqual(meta["root"]["coordinate_order"], "XYZ")
            self.assertEqual(meta["frame"]["vc_open_data_source_coordinate_level"], 0)
            # villa's reader: consecutive blocks share one point, 2..257 points each, exact bounds, counts agree
            for fid, count, *bnd in db.execute("SELECT id, point_count, min_x, min_y, min_z, max_x, max_y, max_z FROM fibers"):
                blobs = [b for (b,) in db.execute("SELECT points FROM blocks WHERE fiber_id=? ORDER BY first_segment", (fid,))]
                prev, n = None, 0
                for b in blobs:
                    self.assertTrue(2 <= len(b) // 24 <= 257)
                    if prev is not None:
                        self.assertEqual(b[:24], prev)
                    prev = b[-24:]
                    n += len(b) // 24 - 1
                self.assertEqual(n + 1, count)
                pts = np.frombuffer(b"".join([blobs[0]] + [x[24:] for x in blobs[1:]]), "<f8").reshape(-1, 3)
                self.assertTrue(np.array_equal(np.concatenate([pts.min(0), pts.max(0)]), np.array(bnd)))
            conf = db.execute("SELECT confidence FROM weft_fibers").fetchall()
            self.assertEqual(conf, [(0.7,)])
            ann = json.loads(db.execute("SELECT annotation FROM fibers WHERE id=1").fetchone()[0])
            self.assertEqual(ann["weft"]["confidence"], 0.7)
            db.close()
            got = w.read_afv(out)
            self.assertEqual(len(got), 2)
            self.assertTrue(np.array_equal(got[0][2], long_))
            # box read through the rtree
            self.assertEqual([g[0] for g in w.read_afv(out, np.array([0, 0, 0]), np.array([3, 3, 4]))], [2])

    def test_bridge_spans(self):
        p = np.stack([np.arange(10.0), np.zeros(10), np.zeros(10)], 1)
        bridged = np.zeros(10, bool)
        bridged[4:7] = True
        self.assertEqual(w.bridge_spans(p, p, bridged), [[4, 6]])
        runs = w.clip_runs(p, np.array([5.5, -1, -1]), np.array([20.0, 1, 1]))   # starts inside the bridge
        self.assertEqual(w.bridge_spans(runs[0], p, bridged), [[0, 1]])
        self.assertEqual(w.bridge_spans(p, p, np.zeros(10, bool)), [])

    def test_clip_runs(self):
        p = np.stack([np.linspace(0, 100, 101), np.full(101, 5.0), np.full(101, 5.0)], 1)
        runs = w.clip_runs(p, np.array([10.0, 0, 0]), np.array([20.0, 10, 10]))
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(runs[0][0, 0], 10.0)
        self.assertAlmostEqual(runs[0][-1, 0], 20.0)


if __name__ == "__main__":
    unittest.main()
