"""kit/switchfix.py (detect, repair, planted splice, random cuts) and the verdict of scripts/unwrap/switchfix_measure.py
on synthetic surfaces. Sheets are planes x = const in a small (z, y, x) prediction volume, 5 voxels thick; a trace is
a grid in the (y, z) plane. No CT, no published data, no network.
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# The measurement script and the frozen rule's records (scripts/unwrap, docs/evidence) are not in every checkout
HAVE_MEASURE = all((REPO / p).is_file() for p in ("scripts/unwrap/switchfix_measure.py", "docs/switchfix.md",
                                                  "docs/evidence/unwrap/2026-10-09-switchfix-rule.json"))
sys.path.insert(0, str(REPO))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
try:
    import scipy.sparse  # noqa: F401
    import scipy.spatial  # noqa: F401
    HAVE_SCIPY = True
except ImportError:  # pragma: no cover
    HAVE_SCIPY = False

if np is not None and HAVE_SCIPY:
    from kit import switchfix as sf

H, W, STEP, Y0, Z0 = 30, 40, 4.0, 10.0, 10.0
SHAPE = (140, 180, 100)                     # z, y, x
A_X, B_X = 40, 54                           # two sheets 14 voxels apart (one winding step)


def need():
    if np is None or not HAVE_SCIPY:
        raise unittest.SkipTest("needs numpy and scipy")


def volume(sheets):
    """A prediction with one 5-voxel-thick sheet per entry: an int x for a plane, or a function (row, col) -> x of the
    trace grid (the sheet then follows that shape in y and z)."""
    vol = np.zeros(SHAPE, np.uint8)
    zz = np.arange(SHAPE[0])
    yy = np.arange(SHAPE[1])
    rr = np.clip(np.rint((zz - Z0) / STEP).astype(int), 0, H - 1)
    cc = np.clip(np.rint((yy - Y0) / STEP).astype(int), 0, W - 1)
    for s in sheets:
        if callable(s):
            X = np.array([[s(r, c) for c in range(W)] for r in range(H)], float)
            xc = np.rint(X[rr][:, cc]).astype(int)              # (z, y)
        else:
            xc = np.full((SHAPE[0], SHAPE[1]), int(s))
        for d in range(-2, 3):
            z, y = np.nonzero(np.ones_like(xc, bool))
            x = np.clip(xc[z, y] + d, 0, SHAPE[2] - 1)
            vol[z, y, x] = 255
    return vol


def grid(xfun):
    rr, cc = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    x = np.array([[xfun(r, c) for c in range(W)] for r in range(H)], float)
    return np.stack([x, Y0 + cc * STEP, Z0 + rr * STEP], -1), np.ones((H, W), bool)


def seed_left(xyz):
    return xyz[H // 2, 5]


def b_bend(c, lo=18, hi=22, near=46.0, ramp=4):
    """Sheet B's x along a column: 54, coming down to 46 (6 voxels from A) for columns lo..hi."""
    if lo <= c <= hi:
        return near
    d = (lo - c) if c < lo else (c - hi)
    return near + (B_X - near) * min(1.0, d / ramp)


class Profiles(unittest.TestCase):
    def setUp(self):
        need()

    def row(self, on_offsets, half=24):
        fg = np.zeros((1, 2 * half + 1), bool)
        for a, b in on_offsets:
            fg[0, half + a:half + b + 1] = True
        return fg

    def test_single_sheet_is_clear(self):
        prof = sf.classify_profiles(self.row([(-2, 2)]))
        self.assertTrue(prof["on"][0])
        self.assertEqual(prof["thickness"][0], 5)
        self.assertEqual(prof["centre"][0], 0)
        cls, st = sf.vertex_classes(prof, np.ones((1, 1), bool))
        self.assertEqual(cls[0, 0], sf.CLEAR)

    def test_companion_within_8_is_contact_and_beyond_is_not(self):
        near = sf.classify_profiles(self.row([(-2, 2), (5, 9)]))       # centres 0 and 7
        far = sf.classify_profiles(self.row([(-2, 2), (12, 16)]))      # centres 0 and 14
        self.assertEqual(sf.vertex_classes(near, np.ones((1, 1), bool))[0][0, 0], sf.CONTACT)
        self.assertEqual(sf.vertex_classes(far, np.ones((1, 1), bool))[0][0, 0], sf.CLEAR)
        self.assertEqual(far["d_pos"][0], 14)

    def test_merged_run_is_contact(self):
        fg = np.concatenate([self.row([(-2, 2)]) for _ in range(9)] + [self.row([(-2, 7)])])
        prof = sf.classify_profiles(fg)
        cls, st = sf.vertex_classes(prof, np.ones((1, 10), bool))
        self.assertEqual(st["median_thickness_vox"], 5)
        self.assertEqual(list(cls[0]), [sf.CLEAR] * 9 + [sf.CONTACT])

    def test_off_sheet_beyond_tolerance(self):
        self.assertFalse(sf.classify_profiles(self.row([(6, 10)]))["on"][0])
        self.assertTrue(sf.classify_profiles(self.row([(4, 8)]))["on"][0])     # within 4 voxels

    def test_sampler_reads_nearest_voxel(self):
        vol = volume([A_X])
        s = sf.ArraySampler(vol)
        fg = sf.profiles(np.array([[A_X + 0.4, 50.0, 50.0]]), np.array([[1.0, 0.0, 0.0]]), s, half=8)
        self.assertEqual(np.flatnonzero(fg[0]).tolist(), [6, 7, 8, 9, 10])


class SheetJumps(unittest.TestCase):
    def setUp(self):
        need()

    def test_curved_sheet_has_none_and_a_step_is_cut(self):
        xyz, valid = grid(lambda r, c: 40 + 0.02 * (c - 20) ** 2)
        h, v = sf.sheet_jump_edges(xyz, valid, 7.0)
        self.assertEqual(int(h.sum() + v.sum()), 0)
        xyz2, _ = grid(lambda r, c: 40.0 if c < 20 else 54.0)
        h, v = sf.sheet_jump_edges(xyz2, valid, 7.0)
        self.assertTrue(h[:, 19].all())
        self.assertEqual(int(h.sum() - h[:, 19].sum()), 0)
        self.assertEqual(int(v.sum()), 0)


class Detect(unittest.TestCase):
    def setUp(self):
        need()

    def test_clean_trace_flags_nothing(self):
        xyz, valid = grid(lambda r, c: float(A_X))
        s, a = sf.detect(xyz, valid, sf.ArraySampler(volume([A_X, B_X])), seed_left(xyz))
        self.assertEqual(s["flagged"], 0)
        self.assertEqual(s["classes"]["clear"], H * W)
        self.assertEqual(s["median_neighbour_step_vox"], 14.0)

    def test_smooth_ramp_onto_the_next_sheet_is_flagged(self):
        xyz, valid = grid(lambda r, c: float(A_X))
        tgt = xyz.copy()
        tgt[..., 0] = B_X
        sx, sv, f = sf.splice(xyz, valid, tgt, valid, 20, 6)
        s, a = sf.detect(sx, sv, sf.ArraySampler(volume([A_X, B_X])), seed_left(xyz))
        self.assertTrue(a["flagged"][f >= 1].all())
        self.assertFalse(a["flagged"][f == 0].any())
        # the jump test alone does not see the seam: the planted seam is smooth
        s0, a0 = sf.detect(sx, sv, None, seed_left(xyz))
        self.assertEqual(s0["flagged"], 0)

    def test_abrupt_seam_and_the_jump_test_alone(self):
        # the planted test's validity check (rule condition 6) can fail: on a 20-voxel grid, as the traces have, the
        # jump test alone catches an abrupt 30-voxel seam. It misses an abrupt 14-voxel one: the central-difference
        # normals at the two ends tilt across the step (offset 6.6 voxels, under 7). The sheet-jump test, which
        # uses no normal, is what catches such a step when the prediction is read (next test).
        rr, cc = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
        xyz = np.stack([np.full((H, W), 40.0), 10 + cc * 20.0, 10 + rr * 20.0], -1)
        valid = np.ones((H, W), bool)
        for step, caught in ((30.0, True), (14.0, False)):
            tgt = xyz.copy()
            tgt[..., 0] += step
            sx, sv, f = sf.splice(xyz, valid, tgt, valid, 20, 0)
            s0, a0 = sf.detect(sx, sv, None, xyz[H // 2, 5])
            self.assertEqual(bool(a0["flagged"][f >= 1].all()), caught, step)
            self.assertEqual(s0["jump_edges"] > 0, caught, step)

    def test_abrupt_step_between_sheets_is_cut_by_the_sheet_jump_test(self):
        xyz, valid = grid(lambda r, c: float(A_X))
        tgt = xyz.copy()
        tgt[..., 0] = B_X
        sx, sv, f = sf.splice(xyz, valid, tgt, valid, 20, 0)
        s, a = sf.detect(sx, sv, sf.ArraySampler(volume([A_X, B_X])), seed_left(xyz))
        self.assertGreater(s["sheet_jump_edges"], 0)
        self.assertTrue(a["flagged"][f >= 1].all())
        self.assertFalse(a["flagged"][:, :18].any())        # the column next to the step may go with it

    def test_switch_through_a_contact_zone_is_flagged(self):
        vol = volume([A_X, lambda r, c: b_bend(c)])
        xyz, valid = grid(lambda r, c: float(A_X) if c < 20 else b_bend(c))
        s, a = sf.detect(xyz, valid, sf.ArraySampler(vol), seed_left(xyz))
        self.assertGreater(s["classes"]["contact"], 0)
        self.assertTrue(a["flagged"][:, 27:].all())          # on B, past the contact band
        self.assertFalse(a["flagged"][:, :15].any())         # the seed side stays
        self.assertGreater(s["cut_components"], 0)

    def test_contact_patch_that_leads_nowhere_is_given_back(self):
        vol = volume([A_X, lambda r, c: 46.0 if (10 <= r <= 15 and 25 <= c <= 30) else float(B_X)])
        xyz, valid = grid(lambda r, c: float(A_X))
        s, a = sf.detect(xyz, valid, sf.ArraySampler(vol), seed_left(xyz))
        self.assertGreater(s["classes"]["contact"], 0)
        self.assertEqual(s["flagged"], 0)
        self.assertGreater(s["given_back_vertices"], 0)

    def test_known_gap_an_off_sheet_end_is_kept(self):
        # Found in review (9 Oct 2026), frozen behaviour pinned here so that changing it is a conscious new version:
        # a trace that steps off its sheet into space the prediction leaves empty, and ends there, touches no other
        # clear component, so the give-back step restores it whole. On a 4-voxel grid not even a 40-voxel step is a
        # jump edge (the central-difference normals tilt across it), and give-back ignores jump edges anyway.
        for dx in (14.0, 40.0):
            xyz, valid = grid(lambda r, c, dx=dx: float(A_X) if c < 20 else A_X + dx)
            s, a = sf.detect(xyz, valid, sf.ArraySampler(volume([A_X])), seed_left(xyz))
            self.assertEqual(s["classes"]["off_sheet"], H * 20, dx)      # the whole far side is off every sheet
            self.assertEqual(s["flagged"], 0, dx)                          # and none of it is flagged
            self.assertGreaterEqual(s["given_back_vertices"], H * 20, dx)

    def test_hole_across_the_trace_cuts_a_correct_part(self):
        # the documented cost: a band where the prediction is empty right across the trace
        vol = volume([A_X, B_X])
        y0, y1 = int(Y0 + 25 * STEP) - 1, int(Y0 + 27 * STEP) + 2
        vol[:, y0:y1, :] = 0
        xyz, valid = grid(lambda r, c: float(A_X))
        s, a = sf.detect(xyz, valid, sf.ArraySampler(vol), seed_left(xyz))
        self.assertTrue(a["flagged"][:, 28:].all())
        self.assertGreater(s["flagged_share"], 0.2)          # an unspliced window can fail the 20 % bound

    def test_seed_on_a_speck_takes_the_largest_component_nearby(self):
        vol = volume([A_X, B_X])
        xyz, valid = grid(lambda r, c: float(A_X))
        # off-sheet ring around the seed vertex
        r, c = H // 2, 5
        ring = np.zeros((H, W), bool)
        ring[r - 1:r + 2, c - 1:c + 2] = True
        ring[r, c] = False
        xyz[ring, 0] = 70.0
        s, a = sf.detect(xyz, valid, sf.ArraySampler(vol), xyz[r, c])
        self.assertGreater(s["seed_component_vertices"], H * W // 2)


class Repair(unittest.TestCase):
    def setUp(self):
        need()

    def write_trace(self, root, xyz, valid, seed):
        from kit import surfbench
        p = Path(root) / "trace"
        surfbench.write_tifxyz(p, xyz, valid, {"format": "tifxyz", "type": "seg", "scale": [0.25, 0.25],
                                              "seed": [float(v) for v in seed], "uuid": "trace"})
        return p

    def test_repair_writes_a_copy_and_never_touches_the_input(self):
        xyz, valid = grid(lambda r, c: float(A_X))
        tgt = xyz.copy()
        tgt[..., 0] = B_X
        sx, sv, f = sf.splice(xyz, valid, tgt, valid, 20, 6)
        with tempfile.TemporaryDirectory() as tmp:
            src = self.write_trace(tmp, sx, sv, seed_left(xyz))
            before = {n: hashlib.sha256((src / n).read_bytes()).hexdigest() for n in ("x.tif", "y.tif", "z.tif",
                                                                                     "meta.json")}
            out = Path(tmp) / "fixed"
            rec, arr = sf.repair(src, out, sf.ArraySampler(volume([A_X, B_X])), record_path=Path(tmp) / "rec.json")
            after = {n: hashlib.sha256((src / n).read_bytes()).hexdigest() for n in before}
            self.assertEqual(before, after)
            self.assertEqual(rec["source_sha256"], before)
            fx, fv, meta = sf.read_surface(out)
            self.assertEqual(fv.shape, (H, W))
            self.assertEqual(int(fv.sum()), rec["detect"]["kept"])
            self.assertFalse(fv[f >= 1].any())
            self.assertTrue(np.allclose(fx[fv], sx[fv]))
            self.assertEqual(meta["uuid"], "fixed")
            self.assertEqual(meta["switchfix"]["params_digest"], sf.params_digest())
            self.assertLess(meta["bbox"][1][1], float(sx[..., 1].max()))
            self.assertEqual(json.loads((Path(tmp) / "rec.json").read_text())["detect"]["flagged"],
                             rec["detect"]["flagged"])
            with self.assertRaises(sf.SwitchFixError):
                sf.repair(src, out, sf.ArraySampler(volume([A_X, B_X])))           # exists
            with self.assertRaises(sf.SwitchFixError):
                sf.repair(src, src / "inner", sf.ArraySampler(volume([A_X, B_X])))  # inside the source
            sf.repair(src, out, sf.ArraySampler(volume([A_X, B_X])), overwrite=True)


def write_zarr(root, vol, chunk=(16, 16, 16)):
    """A one-level OME-Zarr v2 group, uncompressed, '/' keys; all-zero chunks are left out (read as the fill value)."""
    root = Path(root)
    d = root / "0"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".zarray").write_text(json.dumps({
        "zarr_format": 2, "shape": list(vol.shape), "chunks": list(chunk), "dtype": vol.dtype.str,
        "compressor": None, "fill_value": 0, "filters": None, "order": "C", "dimension_separator": "/"}))
    for i in range(-(-vol.shape[0] // chunk[0])):
        for j in range(-(-vol.shape[1] // chunk[1])):
            for m in range(-(-vol.shape[2] // chunk[2])):
                blk = np.zeros(chunk, vol.dtype)
                sub = vol[i * chunk[0]:(i + 1) * chunk[0], j * chunk[1]:(j + 1) * chunk[1],
                          m * chunk[2]:(m + 1) * chunk[2]]
                blk[:sub.shape[0], :sub.shape[1], :sub.shape[2]] = sub
                if not blk.any():
                    continue
                q = d / str(i) / str(j)
                q.mkdir(parents=True, exist_ok=True)
                (q / str(m)).write_bytes(blk.tobytes())
    (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (root / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4", "axes": [{"name": a} for a in "zyx"],
                                                               "datasets": [{"path": "0", "coordinateTransformations": [
                                                                   {"type": "scale", "scale": [1.0, 1.0, 1.0]}]}]}]}))
    return root


def chunk_reader(vol, chunk, drop=()):
    """A read(idx) over a numpy volume: full-size chunks padded with zeros at the far edges, None for `drop`."""
    def read(idx):
        if tuple(idx) in drop:
            return None
        blk = np.zeros(chunk, vol.dtype)
        sl = tuple(slice(i * c, (i + 1) * c) for i, c in zip(idx, chunk))
        sub = vol[sl]
        blk[:sub.shape[0], :sub.shape[1], :sub.shape[2]] = sub
        return blk
    return read


class Samplers(unittest.TestCase):
    """The chunked reader every real measurement goes through (it had no test before review)."""

    def setUp(self):
        need()

    def test_chunk_sampler_matches_the_array_and_reads_missing_chunks_as_zero(self):
        rng = np.random.default_rng(0)
        vol = rng.integers(0, 256, (37, 29, 23), dtype=np.uint8)          # not a multiple of the chunk size
        chunk = (8, 8, 8)
        drop = {(1, 1, 1), (4, 3, 2)}
        cs = sf.ChunkSampler(chunk_reader(vol, chunk, drop), chunk, vol.shape, workers=3)
        expect = vol.copy()
        for c in drop:
            expect[tuple(slice(i * k, (i + 1) * k) for i, k in zip(c, chunk))] = 0
        pts = np.concatenate([rng.integers(-3, 40, (4000, 3)), [[36, 28, 22], [0, 0, 0], [37, 0, 0], [-1, 5, 5]]])
        got = cs.values(pts)
        want = sf.ArraySampler(expect).values(pts)
        self.assertTrue(np.array_equal(got, want))
        self.assertEqual(got[-2], 0)                                       # outside reads 0
        self.assertGreater(cs.chunks_read, 0)

    def test_uint16_values_are_not_wrapped(self):
        vol = np.zeros((16, 16, 16), np.uint16)
        vol[5, 5, 5] = 300                                                 # 300 % 256 = 44, under the threshold
        cs = sf.ChunkSampler(chunk_reader(vol, (8, 8, 8)), (8, 8, 8), vol.shape)
        self.assertEqual(float(cs.values([[5, 5, 5]])[0]), 300.0)
        fg = sf.profiles(np.array([[5.0, 5.0, 5.0]]), np.array([[1.0, 0.0, 0.0]]), cs, half=2)
        self.assertTrue(fg[0, 2])

    def test_retrying_read(self):
        calls = []

        def flaky(idx):
            calls.append(idx)
            if len(calls) < 3:
                raise OSError("cut off")
            return "chunk"
        self.assertEqual(sf._retrying(flaky, tries=4, wait=0.0)((0, 0, 0)), "chunk")
        calls.clear()
        with self.assertRaises(OSError):
            sf._retrying(flaky, tries=2, wait=0.0)((0, 0, 0))

    def test_open_prediction_reads_a_local_ome_zarr(self):
        vol = volume([A_X, B_X])
        xyz, valid = grid(lambda r, c: float(A_X))
        normals = np.tile([1.0, 0.0, 0.0], (H * W, 1))
        with tempfile.TemporaryDirectory() as tmp:
            z = write_zarr(Path(tmp) / "pred.zarr", vol)
            samp = sf.open_prediction(str(z), workers=2)
            got = sf.profiles(xyz.reshape(-1, 3), normals, samp)
        want = sf.profiles(xyz.reshape(-1, 3), normals, sf.ArraySampler(vol))
        self.assertTrue(np.array_equal(got, want))
        self.assertTrue(got.any())


class CliRuns(unittest.TestCase):
    """`python -m kit switchfix detect / repair / params` end to end on a local prediction (no network)."""

    def setUp(self):
        need()

    def run_cli(self, argv):
        import contextlib
        import io
        from kit import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(argv)
        return code, buf.getvalue()

    def test_detect_repair_and_params(self):
        from kit import surfbench
        xyz, valid = grid(lambda r, c: float(A_X))
        tgt = xyz.copy()
        tgt[..., 0] = B_X
        sx, sv, f = sf.splice(xyz, valid, tgt, valid, 20, 6)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            z = write_zarr(tmp / "pred.zarr", volume([A_X, B_X]))
            src = tmp / "trace"
            surfbench.write_tifxyz(src, sx, sv, {"format": "tifxyz", "type": "seg", "scale": [0.25, 0.25],
                                                 "seed": [float(v) for v in seed_left(xyz)], "uuid": "trace"})
            before = {n: hashlib.sha256((src / n).read_bytes()).hexdigest() for n in ("x.tif", "meta.json")}
            code, out = self.run_cli(["switchfix", "detect", str(src), "--prediction", str(z), "--json",
                                      "--out", str(tmp / "sub" / "detect.json")])
            self.assertEqual(code, 0)
            summ = json.loads(out)
            self.assertEqual(summ, json.loads((tmp / "sub" / "detect.json").read_text()))
            api, arr = sf.detect(sx, sv, sf.ArraySampler(volume([A_X, B_X])), seed_left(xyz))
            self.assertEqual(summ["flagged"], api["flagged"])
            self.assertTrue(arr["flagged"][f >= 1].all() and not arr["flagged"][f == 0].any())
            code, out = self.run_cli(["switchfix", "repair", str(src), str(tmp / "fixed"), "--prediction", str(z),
                                      "--record", str(tmp / "rec.json"), "--json"])
            self.assertEqual(code, 0)
            rec = json.loads((tmp / "rec.json").read_text())
            self.assertEqual(rec["detect"]["kept"], api["kept"])
            fx, fv, meta = sf.read_surface(tmp / "fixed")
            self.assertFalse(fv[f >= 1].any())
            self.assertTrue(fv[f == 0].all())
            self.assertEqual({n: hashlib.sha256((src / n).read_bytes()).hexdigest() for n in before}, before)
            code, _ = self.run_cli(["switchfix", "repair", str(src), str(tmp / "fixed"), "--prediction", str(z)])
            self.assertEqual(code, 2)                                      # exists, no --overwrite
            code, out = self.run_cli(["switchfix", "params"])
            self.assertEqual((code, json.loads(out)["digest"]), (0, sf.params_digest()))


@unittest.skipUnless(HAVE_MEASURE, "the switchfix measurement and its rule records are not here")
class RandomCuts(unittest.TestCase):
    def setUp(self):
        need()

    def test_blobs_have_the_sizes_and_spare_the_seed(self):
        valid = np.ones((H, W), bool)
        valid[:, 30] = False
        rem = sf.random_cut(valid, [50, 20, 7], np.random.default_rng(3), protect=(5, 5))
        self.assertEqual(int(rem.sum()), 77)
        self.assertFalse(rem[5, 5])
        self.assertFalse((rem & ~valid).any())
        again = sf.random_cut(valid, [50, 20, 7], np.random.default_rng(3), protect=(5, 5))
        self.assertTrue((rem == again).all())
        self.assertEqual(sorted(sf.removed_blobs(valid, valid & ~rem)), sorted(sf.removed_blobs(valid, valid & ~rem)))
        self.assertEqual(sum(sf.removed_blobs(valid, valid & ~rem)), 77)

    def test_the_control_passes_a_real_repair_and_fails_a_sham(self):
        M = load_measure()
        valid = np.ones((H, W), bool)
        S = valid.copy()
        L = np.where(np.arange(W)[None, :] < 30, 1, 2).repeat(H, 0)      # columns 30 on: another winding
        p0, dom = M.precision_of(valid, S, L)
        self.assertEqual(dom, 1)
        real = valid & (np.arange(W)[None, :] < 30)
        sham = valid & (np.arange(W)[None, :] >= 10)                     # removes as much, on the right winding
        blobs = sf.removed_blobs(valid, real)
        self.assertEqual(blobs, sf.removed_blobs(valid, sham))
        gains = []
        for seed in range(20):
            rem = sf.random_cut(valid, blobs, np.random.default_rng(seed), protect=(H // 2, 5))
            gains.append(M.precision_of(valid & ~rem, S, L)[0] - p0)
        p95 = float(np.percentile(gains, 95))
        self.assertGreater(M.precision_of(real, S, L)[0] - p0, p95)
        self.assertLessEqual(M.precision_of(sham, S, L)[0] - p0, p95)


def load_measure():
    spec = importlib.util.spec_from_file_location("switchfix_measure",
                                                  REPO / "scripts" / "unwrap" / "switchfix_measure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_MEASURE, "the switchfix measurement and its rule records are not here")
class Verdict(unittest.TestCase):
    def setUp(self):
        need()
        self.M = load_measure()

    def planted(self, root, spliced_share=0.9, clean_share=0.05, jump_share=0.0, ab=("w045", "w044"),
                n_windows=3, rule=None):
        p = Path(root) / "planted.json"
        p.write_text(json.dumps({"A": ab[0], "B": ab[1], "rule": rule or self.M.RULE["planted"],
                                 "windows_requested": n_windows, "windows": [{}] * n_windows,
                                 "pooled": {"spliced": 1000, "spliced_flagged": int(1000 * spliced_share),
                                            "clean": 3000, "clean_flagged": int(3000 * clean_share),
                                            "jump_only_flagged": int(1000 * jump_share),
                                            "spliced_flagged_share": spliced_share,
                                            "clean_flagged_share": clean_share,
                                            "jump_only_spliced_share": jump_share}}))
        return p

    def trace(self, root, name, pb=0.87, pa=0.95, swb=74, swa=3, covb=8.9, cova=8.0, p95=0.01, lab_after=None,
              valid=True, params_digest=None, sb_digest=None, surface=None):
        def m(p, sw, cov):
            return {"dominant": "w045", "d4": {"dominant_precision": p}, "switches": {"switch_edges": sw},
                    "dominant_covered_cm2": cov}
        dig = sb_digest or self.M.SURFBENCH_RULE_DIGEST
        p = Path(root) / f"{name}.json"
        p.write_text(json.dumps({
            "surface": surface or name, "params_digest": params_digest or self.M.FROZEN_PARAMS_DIGEST,
            "before": {"valid": valid, "rule_digest": dig, "metrics": m(pb, swb, covb) if valid else None},
            "after": {"valid": True, "rule_digest": self.M.SURFBENCH_RULE_DIGEST, "metrics": m(pa, swa, cova)},
            "control_gain_p95": p95,
            "labels_check": {"precision_before_from_labels": pb,
                             "precision_after_from_labels": pa if lab_after is None else lab_after}}))
        return p

    def judge(self, planted, traces, rule_sha="x" * 64, rule_doc=None):
        with tempfile.TemporaryDirectory() as tmp:
            pl = planted(tmp)
            ts = [t(tmp) for t in traces]
            return self.M.verdict(rule_sha, pl, ts, Path(tmp) / "v.json", rule_doc=rule_doc)

    def test_pass(self):
        r = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a")])
        self.assertEqual(r["verdict"], "PASS")

    def test_each_condition_can_fail(self):
        cases = {
            "precision": dict(pa=0.86),
            "switches": dict(swa=80),
            "area": dict(cova=7.0),              # 7.0 / 8.9 < 0.80
            "controls": dict(p95=0.2),           # gain 0.08 under the controls' 95th percentile
        }
        for name, kw in cases.items():
            r = self.judge(lambda d: self.planted(d), [lambda d, kw=kw: self.trace(d, "a", **kw)])
            self.assertEqual(r["verdict"], "FAIL", name)
        r = self.judge(lambda d: self.planted(d, spliced_share=0.5), [lambda d: self.trace(d, "a")])
        self.assertEqual(r["verdict"], "FAIL")
        r = self.judge(lambda d: self.planted(d, clean_share=0.3), [lambda d: self.trace(d, "a")])
        self.assertEqual(r["verdict"], "FAIL")

    def test_invalid_cases(self):
        r = self.judge(lambda d: self.planted(d, jump_share=0.5), [lambda d: self.trace(d, "a")])
        self.assertEqual(r["verdict"], "INVALID")                         # seam not smooth
        r = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a", lab_after=0.90)])
        self.assertEqual(r["verdict"], "INVALID")                         # labels do not reproduce the score
        r = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a", valid=False)])
        self.assertEqual(r["verdict"], "INVALID")
        r = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a", swb=0, swa=0)])
        self.assertEqual(r["verdict"], "INVALID")                         # nothing to repair anywhere

    def test_a_trace_without_switches_does_not_count(self):
        r = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a"),
                                                lambda d: self.trace(d, "b", swb=0, swa=0, pa=0.87)])
        self.assertEqual(r["verdict"], "PASS")

    def test_records_not_made_under_the_frozen_rule_are_invalid(self):
        # review additions: each check enforces a digest or constant the rule text names, and each can fail
        ok = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a")])
        self.assertEqual((ok["verdict"], ok["invalid_reasons"]), ("PASS", []))
        cases = {
            "params": ([lambda d: self.trace(d, "a", params_digest="0" * 64)], lambda d: self.planted(d)),
            "surfbench rule": ([lambda d: self.trace(d, "a", sb_digest="1" * 64)], lambda d: self.planted(d)),
            "windings": ([lambda d: self.trace(d, "a")], lambda d: self.planted(d, ab=("w038", "w037"))),
            "windows": ([lambda d: self.trace(d, "a")], lambda d: self.planted(d, n_windows=1)),
            "planted constants": ([lambda d: self.trace(d, "a")],
                                  lambda d: self.planted(d, rule={**self.M.RULE["planted"], "ramp": 2})),
            "twice": ([lambda d: self.trace(d, "a"), lambda d: self.trace(d, "b", surface="a")],
                      lambda d: self.planted(d)),
        }
        for name, (traces, planted) in cases.items():
            r = self.judge(planted, traces)
            self.assertEqual(r["verdict"], "INVALID", name)
            self.assertTrue(r["invalid_reasons"], name)

    def test_rule_doc_hash_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "rule.md"
            doc.write_text("intro\n<!-- switchfix-rule:begin -->\nRule text.\n<!-- switchfix-rule:end -->\n")
            sha = hashlib.sha256(b"Rule text.\n").hexdigest()
            self.assertEqual(self.M.rule_text_sha256(doc), sha)
            good = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a")], rule_sha=sha, rule_doc=doc)
            self.assertEqual(good["verdict"], "PASS")
            doc.write_text("intro\n<!-- switchfix-rule:begin -->\nRule text, loosened.\n<!-- switchfix-rule:end -->\n")
            bad = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a")], rule_sha=sha, rule_doc=doc)
            self.assertEqual(bad["verdict"], "INVALID")

    def test_invalid_score_without_metrics_does_not_crash(self):
        r = self.judge(lambda d: self.planted(d), [lambda d: self.trace(d, "a", valid=False)])
        self.assertEqual(r["verdict"], "INVALID")
        self.assertIsNone(r["traces"][0]["conditions"])


@unittest.skipUnless(HAVE_MEASURE, "the switchfix measurement and its rule records are not here")
class FrozenRecords(unittest.TestCase):
    """The rule text, the measurement constants and the detector parameters still hash to what was recorded when
    the rule was fixed (docs/evidence/unwrap/2026-10-09-switchfix-rule.json). A failure here means a frozen record
    changed; a new rule needs a new version and a new evidence file, not an edit."""

    def setUp(self):
        need()
        self.M = load_measure()
        self.ev = json.loads((REPO / "docs" / "evidence" / "unwrap" / "2026-10-09-switchfix-rule.json").read_text())

    def test_rule_text_hash(self):
        self.assertEqual(self.M.rule_text_sha256(), self.ev["rule_sha256"])

    def test_measure_rule_and_params_digests(self):
        self.assertEqual(hashlib.sha256(sf.canonical(self.M.RULE).encode()).hexdigest(),
                         self.ev["measure_rule_digest"])
        self.assertEqual(sf.params_digest(), self.ev["params_digest"])
        self.assertEqual(self.M.FROZEN_PARAMS_DIGEST, self.ev["params_digest"])
        self.assertEqual(self.M.SURFBENCH_RULE_DIGEST, self.ev["surfbench_rule_digest"])

    def test_surfbench_rule_unchanged(self):
        from kit import surfbench
        self.assertEqual(surfbench.RULE_DIGEST, self.M.SURFBENCH_RULE_DIGEST)

    def test_rule_text_names_the_digests_it_pins(self):
        text = (REPO / "docs" / "switchfix.md").read_text(encoding="utf-8")
        body = text[text.index(self.M.RULE_MARKERS[0]):text.index(self.M.RULE_MARKERS[1])]
        self.assertIn(self.M.FROZEN_PARAMS_DIGEST, body)
        self.assertIn(self.M.SURFBENCH_RULE_DIGEST[:12], body)


@unittest.skipUnless(HAVE_MEASURE, "the switchfix measurement and its rule records are not here")
class MeasureHelpers(unittest.TestCase):
    def setUp(self):
        need()
        self.M = load_measure()

    def test_seed_cell(self):
        valid = np.ones((100, 100), bool)
        self.assertEqual(self.M.seed_cell(valid, 50, 25, 47), (50, 25))
        valid[48:53, 23:28] = False
        r, c = self.M.seed_cell(valid, 50, 25, 47)
        self.assertTrue(valid[r, c] and c < 47)
        self.assertEqual(abs(r - 50) + abs(c - 25), 3)                   # nearest valid, not the grid centre
        with self.assertRaises(ValueError):
            self.M.seed_cell(np.zeros((100, 100), bool), 50, 25, 47)

    def test_surfbench_cli_refuses_stale_scores_and_missing_selfcross(self):
        import contextlib
        import io
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            out = Path(tmp) / "score.json"
            with mock.patch.dict(os.environ, {"VC_BIN": ""}):
                with self.assertRaises(RuntimeError):                     # VC_BIN unset
                    self.M.surfbench_cli(Path(tmp), out)
            with mock.patch.dict(os.environ, {"VC_BIN": "/nowhere"}):
                out.write_text(json.dumps({"valid": True, "metrics": {"selfcross": {"transverse": 0}}}))
                quiet = mock.Mock(returncode=2, stderr="")
                with mock.patch.object(self.M.subprocess, "run", return_value=quiet):
                    with self.assertRaises(RuntimeError):                 # wrote nothing: the stale file is gone
                        self.M.surfbench_cli(Path(tmp), out)

                def writes(score):
                    def run(*a, **k):
                        out.write_text(json.dumps(score))
                        return mock.Mock(returncode=0, stderr="")
                    return run
                with mock.patch.object(self.M.subprocess, "run",
                                       side_effect=writes({"valid": True, "metrics": {
                                           "selfcross": "vc_tifxyz_selfcross not found"}})):
                    with self.assertRaises(RuntimeError):                 # self-intersections not measured
                        self.M.surfbench_cli(Path(tmp), out)
                with mock.patch.object(self.M.subprocess, "run",
                                       side_effect=writes({"valid": True, "metrics": {"selfcross": {"transverse": 3}}})):
                    self.assertEqual(self.M.surfbench_cli(Path(tmp), out)["metrics"]["selfcross"]["transverse"], 3)



class Cli(unittest.TestCase):
    def test_params_digest_is_stable(self):
        need()
        self.assertEqual(sf.params_digest(), hashlib.sha256(sf.canonical(sf.PARAMS).encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
