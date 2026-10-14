"""scripts/umbilicus: the centre network's coordinate frame, augmentation bookkeeping, job names, the end trims and
the range reads."""
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
UMB = os.path.abspath(os.path.join(HERE, "..", "scripts", "umbilicus"))
# The scripts have generic module names (slices, pipeline, predict, ...) and each puts its folder first on sys.path
# when imported. They are imported only while this module's tests run; tearDownModule takes the folder off sys.path
# and the modules out of sys.modules, so no other test imports them by accident.
MODULES = ("slices", "centrenet", "refine", "pipeline", "predict", "endcheck", "ctcheck")
try:
    import numpy as np
except ImportError:
    np = None
try:
    import torch
except ImportError:
    torch = None
if np is None:
    torch = None
centrenet = None


_SHADOWED = {}   # same-named modules another test imported (scripts/strokenet/pipeline.py), put back afterwards


def setUpModule():
    global centrenet
    sys.path.insert(0, UMB)
    for name in MODULES:
        m = sys.modules.get(name)
        if m is not None and os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) != UMB:
            _SHADOWED[name] = sys.modules.pop(name)
    if torch is not None:
        import centrenet as module
        centrenet = module


def tearDownModule():
    while UMB in sys.path:
        sys.path.remove(UMB)
    for name in MODULES:
        m = sys.modules.get(name)
        if m is not None and os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == UMB:
            del sys.modules[name]
    sys.modules.update(_SHADOWED)
    _SHADOWED.clear()


@unittest.skipIf(torch is None, "numpy or torch unavailable")
class CentreNetTest(unittest.TestCase):
    def test_frame_round_trip_and_geometry(self):
        """A bright dot placed in level-3 voxels comes back at the same place through the net frame."""
        ct = np.zeros((3, 300, 420), np.uint8)
        ct[:, 40:260, 60:380] = 20
        y, x = 123, 301
        ct[:, y - 2:y + 3, x - 2:x + 3] = 255
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.npz")
            np.savez(p, ct=ct, z_l0=np.array([0, 64, 128]), vol="P/volumes/1-9.362um-x", um=9.362, level=3)
            im, fr = centrenet.frame(p, 96, device="cpu")
        w = im[1].astype(float); w = w * (w > 0.5 * w.max())
        yy, xx = np.mgrid[:96, :96]
        c = np.array([[(yy * w).sum() / w.sum(), (xx * w).sum() / w.sum()]])
        l0 = centrenet.Frame.net_to_l0(c, fr)
        self.assertLess(abs(l0[0, 0] / 8 - y), 1.0)
        self.assertLess(abs(l0[0, 1] / 8 - x), 1.0)
        a = np.array([[10.0, 20.0], [3.5, 70.25]])
        np.testing.assert_allclose(centrenet.Frame.l0_to_net(centrenet.Frame.net_to_l0(a, fr), fr), a, atol=1e-6)

    def test_augment_moves_the_centre_with_the_image(self):
        rng = np.random.default_rng(0)
        for trial in range(50):
            x = torch.zeros(4, 3, 40, 40)
            t = rng.integers(0, 40, (4, 2)).astype(np.float32)
            for i, (a, b) in enumerate(t):
                x[i, 1, int(a), int(b)] = 1
            out, tt = centrenet.augment(x, t, np.random.default_rng(trial))
            for i in range(4):
                m = out[i, 1] - out[i, 1].min()
                j = np.unravel_index(int(m.argmax()), m.shape)
                self.assertEqual((int(j[0]), int(j[1])), (int(tt[i, 0]), int(tt[i, 1])))

    def test_smooth_z_fills_gaps_and_keeps_a_line(self):
        p = np.stack([np.linspace(0, 50, 40), np.linspace(10, 20, 40)], 1)
        p[5] = np.nan
        q = centrenet.smooth_z(p)
        self.assertTrue(np.isfinite(q).all())
        self.assertLess(np.abs(q - np.stack([np.linspace(0, 50, 40), np.linspace(10, 20, 40)], 1)).max(), 1e-6)

    def test_net_predicts_half_resolution_heatmap(self):
        net = centrenet.Net(4)
        self.assertEqual(tuple(net(torch.zeros(2, 3, 64, 64)).shape), (2, 32, 32))


@unittest.skipIf(torch is None, "numpy or torch unavailable")
class RefineTest(unittest.TestCase):
    def setUp(self):
        import refine
        self.refine = refine

    def test_crop_places_the_window_and_pads_with_zeros(self):
        ct = np.arange(5 * 50 * 60, dtype=np.uint32).reshape(5, 50, 60).astype(np.uint8)
        out, (y0, x0) = self.refine.crop(ct, 2, 10.4, 30.6, 16)
        self.assertEqual((y0, x0), (2, 23))
        np.testing.assert_array_equal(out[1], ct[2, 2:18, 23:39])
        np.testing.assert_array_equal(out[0], ct[1, 2:18, 23:39])
        out, (y0, x0) = self.refine.crop(ct, 0, 3.0, 58.0, 16)   # off the top and right edges; first slice clamped
        self.assertEqual((y0, x0), (-5, 50))
        self.assertTrue((out[:, :5] == 0).all() and (out[:, :, 10:] == 0).all())
        np.testing.assert_array_equal(out[0], out[1])
        np.testing.assert_array_equal(out[1, 5:, :10], ct[0, 0:11, 50:60])

    def test_training_crop_centre_matches_a_dot(self):
        """A dot at the centre stays under the training centre whatever the training offset."""
        r = self.refine
        S, R = r.S, r.R
        ct = np.zeros((3, 600, 600), np.uint8)
        t = np.array([[300.3, 280.7]] * 3)
        ct[1, 300, 281] = 255
        bd, org, tk = r.bands(ct, t)
        rng = np.random.default_rng(0)
        for o in r.train_offsets(rng, 200, 8.64):
            c = tk[1] + o
            y0, x0 = int(round(c[0])) - S // 2 - org[1, 0], int(round(c[1])) - S // 2 - org[1, 1]
            self.assertTrue(0 <= y0 <= 2 * R and 0 <= x0 <= 2 * R)
            win = bd[1, 1, int(y0):int(y0) + S, int(x0):int(x0) + S]
            ty, tx = tk[1] - org[1] - (y0, x0)
            j = np.unravel_index(int(win.argmax()), win.shape)
            self.assertLessEqual(abs(j[0] - ty), 0.5); self.assertLessEqual(abs(j[1] - tx), 0.5)

    def test_offsets_have_the_asked_median(self):
        o = self.refine.smooth_offsets(400, np.random.default_rng(1), 8.64, 1.2)
        mm = np.hypot(*o.T) * 8.64 * 8 / 1000
        self.assertAlmostEqual(float(np.median(mm)), 1.2, places=6)
        self.assertLess(np.abs(np.diff(o, axis=0)).mean(), np.abs(o).mean() / 3)   # smooth along z


class KeepBandTest(unittest.TestCase):
    def test_keep_band_drops_caps_and_mount(self):
        try:
            import pipeline
        except ImportError as e:
            self.skipTest(str(e))
        z = np.arange(100) * 64.0; um = 8.64               # 0.55 mm per slice
        area = np.full(100, 1000.0)
        area[:3] = 5000; area[3:12] = 50; area[-4:] = 30     # cap, mount strip, top strip
        area[80] = 0                                          # one empty slice splits the run
        k = pipeline.keep_band(area, z, um)
        self.assertFalse(k[:12].any() or k[-4:].any())
        self.assertTrue(k[12:80].all())                       # the longer of the two runs
        self.assertFalse(k[80:].any())
        self.assertFalse(pipeline.keep_band(np.zeros(5), np.arange(5) * 64.0, um).any())


def _synthetic_scroll(n=60, end=12, size=(200, 260), um=8.64):
    """A level-3 slice stack of a rolled scroll: rings of papyrus (120) with air (50) between them inside the volume
    mask, 0 outside. The first `end` slices are a broken end (papyrus only below the centre), the last `end` a hollow
    end (no papyrus within 70 px, 4.8 mm, of the centre). Centre at y 100, x 130 level-3 px (y 800, x 1040 level-0),
    off the diagonal so that swapping y and x anywhere moves it into the papyrus or off it."""
    yy, xx = np.mgrid[:size[0], :size[1]]; r = np.hypot(yy - 100, xx - 130)
    body = np.where(r < 85, 50, 0).astype(np.uint8); body[(r < 80) & (r % 6 < 3)] = 120
    ct = np.repeat(body[None], n, 0)
    broken = body.copy(); broken[:110] = 0
    hollow = body.copy(); hollow[(r < 70) & (body == 120)] = 50
    ct[:end] = broken; ct[-end:] = hollow
    z = 32 + 64 * np.arange(n)
    yx = np.tile([800.0, 1040.0], (n, 1))                    # level-0 voxels, (y, x)
    return ct, z, yx, um


class EndRuleTest(unittest.TestCase):
    def setUp(self):
        try:
            import scipy  # noqa: F401
            import pipeline
        except ImportError as e:
            self.skipTest(str(e))
        self.p = pipeline

    def test_papyrus_level_splits_air_and_papyrus(self):
        ct, *_ = _synthetic_scroll()
        t = self.p.papyrus_level(ct)
        self.assertTrue(50 < t <= 120)
        self.assertEqual(self.p.papyrus_level(np.zeros((2, 5, 5), np.uint8)), 256)

    def test_support_in_body_beside_a_broken_end_and_in_a_hollow(self):
        ct, z, yx, um = _synthetic_scroll()
        thr = self.p.papyrus_level(ct)
        s = self.p.end_support(ct, yx, um, thr)
        self.assertTrue((s[12:-12] == 1).all())               # surrounded by windings
        self.assertTrue((s[:12] < 0.5).all())                 # only the half below the centre has papyrus
        self.assertTrue((s[-12:] == 0).all())                 # hollow wider than the 4 mm radius
        bigger = self.p.end_support(ct[-1:], yx[-1:], um, thr, radius_mm=5.5)
        self.assertEqual(bigger[0], 1.0)                      # a 5.5 mm radius reaches the windings round the hollow
        nan = yx[:2].copy(); nan[0] = np.nan
        self.assertEqual(self.p.end_support(ct[20:22], nan, um, thr)[0], 0.0)

    def test_support_from_windows_matches_whole_slices(self):
        ct, z, yx, um = _synthetic_scroll()
        thr = self.p.papyrus_level(ct)
        win, org = self.p.centre_windows(ct, yx, um)
        self.assertEqual(win.shape[1], 2 * 66)                 # 4.5 mm at 69.12 um per level-3 pixel, rounded up
        whole = self.p.end_support(ct, yx, um, thr)
        np.testing.assert_array_equal(self.p.end_support(win, yx, um, thr, origin=org), whole)
        keep = np.ones(len(z), bool)
        a = self.p.end_trimmed_keep(ct, yx, z, um, keep)
        b = self.p.apply_end_rule(win, org, yx, z, um, keep)
        np.testing.assert_array_equal(a[0], b[0]); np.testing.assert_array_equal(a[1], b[1]); self.assertEqual(a[2], b[2])
        moved = yx + [[0.0, 8 * 3.0]]                         # a centre 3 level-3 px off still sits in the body
        self.assertTrue((self.p.end_support(ct[20:40], moved[20:40], um, thr) == 1).all())

    def test_trim_ends_only_from_the_ends(self):
        z = 64.0 * np.arange(40); um = 8.64                   # 0.55 mm per slice, a 2 mm run is 4 slices
        sup = np.ones(40); keep = np.ones(40, bool)
        sup[:5] = 0.2; sup[-3:] = 0.0                          # unsupported ends
        sup[20:23] = 0.1                                       # a dip in the middle stays
        sup[7] = 0.1                                           # a lone good pair at 5, 6 is not a run of 4
        k = self.p.trim_ends(keep, sup, z, um)
        self.assertFalse(k[:8].any() or k[-3:].any())
        self.assertTrue(k[8:37].all())
        keep[:2] = False                                       # points already dropped stay dropped
        self.assertFalse(self.p.trim_ends(keep, np.ones(40), z, um)[:2].any())
        self.assertFalse(self.p.trim_ends(np.ones(40, bool), np.full(40, 0.5), z, um).any())
        self.assertFalse(self.p.trim_ends(np.zeros(40, bool), sup, z, um).any())

    def test_trim_drops_the_broken_and_hollow_ends_of_written_files(self):
        ct, z, yx, um = _synthetic_scroll()
        with tempfile.TemporaryDirectory() as d:
            np.savez(os.path.join(d, "S.npz"), ct=ct, z_l0=z, um=um, level=3, vol="S/volumes/1-8.640um-x")
            src = os.path.join(d, "src"); os.makedirs(src)
            pts = [dict(x=int(x), y=int(y), z=int(v), score=100) for v, (y, x) in zip(z, yx)]
            with open(os.path.join(src, "S_umbilicus.json"), "w") as fh:
                json.dump(dict(control_points=pts, metadata=dict(voxelsize_um=um, source_volume="S/volumes/1-8.640um-x")), fh)
            band = self.p.trim(src, d, os.path.join(d, "a"), end_rule=False)["S"]["z"]
            ends = self.p.trim(src, d, os.path.join(d, "b"))["S"]["z"]
            with open(os.path.join(d, "b", "S_umbilicus.json")) as fh:
                j = json.load(fh)
            self.assertEqual(ends, [int(z[12]), int(z[-13])])  # first and last slice with papyrus round the centre
            self.assertLess(band[0], ends[0]); self.assertGreater(band[1], ends[1])   # keep_band alone keeps air
            self.assertIn("end-point rule", j["metadata"]["trimmed"])
            import endcheck
            out = endcheck.files(src, os.path.join(d, "c"), cache=os.path.join(d, "cache"), data=d)
            self.assertEqual(out["S"]["points_out"], len(z) - 24)


@unittest.skipIf(torch is None, "numpy or torch unavailable")
class CollectEndRuleTest(unittest.TestCase):
    def test_collected_files_drop_the_broken_and_hollow_ends(self):
        """collect and chain_collect write unlabelled scrolls' files with both end trims (labels and scrolls synthetic)."""
        import pipeline, refine
        ct, z, yx, um = _synthetic_scroll()
        T = np.array([[z[0], *yx[0]], [z[-1], *yx[-1]]])
        present = [True] * len(z)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(pipeline.slices, "LABELLED", ["S"]), mock.patch.object(pipeline.slices, "UNLABELLED", ["U"]), \
                mock.patch.object(pipeline.slices, "truth", lambda s: ("S/volumes/1-8.640um-x", T)):
            for s in ("S", "U"):
                np.savez(os.path.join(d, f"{s}.npz"), ct=ct, z_l0=z, um=um, level=3, vol=f"{s}/volumes/1-8.640um-x")
            p = dict(z=z.tolist(), yx=yx.tolist(), base_yx=yx.tolist(), peak=[1.0] * len(z), present=present, um=um,
                     vol="U/volumes/1-8.640um-x")
            for job, rec in (("fold0s0", dict(job="fold0s0", test=["S"], train_info={}, size=64, width=4, epochs=1)),
                             ("refine_fold0", dict(job="refine_fold0", test=["S"], train_info={}, base="b"))):
                with open(os.path.join(d, f"{job}.json"), "w") as fh:
                    json.dump(dict(rec, preds=dict(S=p, U=p)), fh)
            for res in (pipeline.collect(d, d), refine.chain_collect(d, d)):
                self.assertEqual(res["unlabelled"]["U"]["points"], len(z) - 24)
                with open(os.path.join(d, "umbilicus", "U_umbilicus.json")) as fh:
                    j = json.load(fh)
                zs = [q["z"] for q in j["control_points"]]
                self.assertEqual((min(zs), max(zs)), (int(z[12]), int(z[-13])))
                self.assertEqual({(q["y"], q["x"]) for q in j["control_points"]}, {(800, 1040)})
                self.assertIn("end-point rule", j["metadata"]["method"])

    def test_collect_without_unlabelled_scrolls_writes_no_files(self):
        """With slices.UNLABELLED empty, collect and chain_collect score the held-out scroll and write no umbilicus/
        folder and no "unlabelled" key."""
        import pipeline, refine
        ct, z, yx, um = _synthetic_scroll()
        T = np.array([[z[0], *yx[0]], [z[-1], *yx[-1]]])
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(pipeline.slices, "LABELLED", ["S"]), mock.patch.object(pipeline.slices, "UNLABELLED", []), \
                mock.patch.object(pipeline.slices, "truth", lambda s: ("S/volumes/1-8.640um-x", T)):
            np.savez(os.path.join(d, "S.npz"), ct=ct, z_l0=z, um=um, level=3, vol="S/volumes/1-8.640um-x")
            p = dict(z=z.tolist(), yx=yx.tolist(), base_yx=yx.tolist(), peak=[1.0] * len(z), present=[True] * len(z),
                     um=um, vol="S/volumes/1-8.640um-x")
            for job, rec in (("fold0s0", dict(job="fold0s0", test=["S"], train_info={}, size=64, width=4, epochs=1)),
                             ("refine_fold0", dict(job="refine_fold0", test=["S"], train_info={}, base="b"))):
                with open(os.path.join(d, f"{job}.json"), "w") as fh:
                    json.dump(dict(rec, preds=dict(S=p)), fh)
            for res in (pipeline.collect(d, d), refine.chain_collect(d, d)):
                self.assertIn("S", res["held_out"])
                self.assertNotIn("unlabelled", res)
            self.assertFalse(os.path.exists(os.path.join(d, "umbilicus")))


@unittest.skipIf(torch is None, "numpy or torch unavailable")
class PredictTest(unittest.TestCase):
    def test_predict_writes_a_trimmed_file_from_weights(self):
        """Untrained weights: checks the plumbing (frames, both stages, medians, trims, file format), not accuracy."""
        try:
            import predict
        except ImportError as e:
            self.skipTest(str(e))
        import refine
        ct, z, yx, um = _synthetic_scroll(n=30, end=6)
        ct = ct.copy(); ct[:2] = 0                    # two slices without papyrus: no zoom answer there
        frame, side = predict.FRAME, refine.S
        predict.FRAME, refine.S = 64, 64             # small frames keep the test fast; the plumbing is the same
        self.addCleanup(setattr, predict, "FRAME", frame); self.addCleanup(setattr, refine, "S", side)
        with tempfile.TemporaryDirectory() as d:
            np.savez(os.path.join(d, "S.npz"), ct=ct, z_l0=z, um=um, level=3, vol="S/volumes/1-8.640um-x")
            ws = []
            for i in range(2):
                torch.manual_seed(i); p = os.path.join(d, f"w{i}.pt"); torch.save(centrenet.Net(4).state_dict(), p); ws.append(p)
            r = predict.predict("S", ws, ws, d, os.path.join(d, "out"), end_rule=False)   # two zoom models: a spread
            with open(os.path.join(d, "out", "S_umbilicus.json")) as fh:
                j = json.load(fh)
            self.assertEqual(r["points"], len(j["control_points"]))
            self.assertEqual(j["metadata"]["voxelsize_um"], um)
            self.assertTrue(all(set(p) == {"x", "y", "z", "score"} for p in j["control_points"]))
            self.assertTrue(set(p["z"] for p in j["control_points"]) <= set(int(v) for v in z))
            def no_nan(c):
                raise ValueError(f"{c} is not JSON")
            with open(os.path.join(d, "out", "S_predict.json")) as fh:
                det = json.load(fh, parse_constant=no_nan)          # strict JSON: no NaN
            self.assertEqual(det["spread_mm"][:2], [None, None])
            self.assertEqual(det["kept"], det["keep_band"])
            self.assertEqual(det["first"], ["w0.pt", "w1.pt"]); self.assertEqual(det["zoom"], ["w0.pt", "w1.pt"])


class JobsTest(unittest.TestCase):
    def test_job_names_and_folds(self):
        try:
            import pipeline
        except ImportError as e:
            self.skipTest(str(e))
        self.assertEqual(pipeline.parse_job("fold2s1"), (2, 1))
        self.assertEqual(pipeline.parse_job("alls0"), (None, 0))
        with self.assertRaises(SystemExit):
            pipeline.parse_job("fold9")
        folds = sum(pipeline.FOLDS, [])
        self.assertEqual(len(folds), len(set(folds)))
        self.assertFalse(set(folds) & set(pipeline.slices.UNLABELLED))


class EndRulePromisesTest(unittest.TestCase):
    """The end-point rule's promises: ends only, 2 mm and 4 mm converted per scan, y before x, constants read when
    called, and trim's refusal of points it cannot place."""
    def setUp(self):
        try:
            import scipy  # noqa: F401
            import pipeline
        except ImportError as e:
            self.skipTest(str(e))
        self.p = pipeline

    def test_trim_ends_never_drops_between_survivors(self):
        """Random keep masks (with gaps) and supports. The rule removes points only before its first qualifying run
        and after its last; between them every point is as it was; what survives starts and ends with a full run of
        supported points; and nothing survives when no run qualifies."""
        rng = np.random.default_rng(0); um, bar = 8.64, self.p.END_SUPPORT
        m = 4                                                  # 2 mm at 64 voxels of 8.64 um (0.553 mm) per slice
        for _ in range(1000):
            n = int(rng.integers(1, 60)); z = 64.0 * np.arange(n)
            keep = rng.random(n) < rng.uniform(0.5, 1.0)
            sup = np.where(rng.random(n) < rng.uniform(0.2, 0.95), 1.0, rng.random(n) * bar)
            k = self.p.trim_ends(keep, sup, z, um)
            self.assertFalse((k & ~keep).any())
            kept = np.nonzero(keep)[0]
            run = [p for p in range(len(kept) - m + 1) if (sup[kept[p:p + m]] >= bar).all()]
            idx = np.nonzero(k)[0]
            self.assertEqual(bool(len(idx)), bool(run))
            if len(idx):
                np.testing.assert_array_equal(k[idx[0]:idx[-1] + 1], keep[idx[0]:idx[-1] + 1])
                first, last = list(kept).index(idx[0]), list(kept).index(idx[-1])
                self.assertEqual((first, last), (run[0], run[-1] + m - 1))

    def test_run_is_2_mm_of_slices_for_each_voxel_size(self):
        for um, step, m in ((8.64, 64, 4), (9.362, 64, 4), (2.4, 64, 14), (8.64, 128, 2)):
            z = step * np.arange(40.0)
            for r, kept in ((m - 1, False), (m, True)):
                s = np.zeros(40); s[10:10 + r] = 1
                self.assertEqual(self.p.trim_ends(np.ones(40, bool), s, z, um).any(), kept, (um, step, r))

    def test_radius_is_4_mm_for_each_voxel_size_and_level(self):
        """A ring of papyrus whose inner edge is 3.85 mm from the centre counts, one at 4.15 mm does not, whole slices
        or windows, at both voxel sizes and levels 2 and 3."""
        for um in (8.64, 9.362):
            for level in (2, 3):
                f = 2 ** level; px = um * f / 1000; H = int(12 / px) + 1; c = H // 2
                r = np.hypot(*(np.mgrid[:H, :H] - c)) * px
                for inner, want in ((3.85, 1.0), (4.15, 0.0)):
                    im = np.where(r < 5.9, 50, 0).astype(np.uint8); im[(r >= inner) & (r < inner + 0.4)] = 120
                    yx = np.array([[c * f, c * f]], float); thr = self.p.papyrus_level(im[None])
                    w, org = self.p.centre_windows(im[None], yx, um, level=level)
                    self.assertEqual(self.p.end_support(w, yx, um, thr, level=level, origin=org)[0], want, (um, level, inner))
                    self.assertEqual(self.p.end_support(im[None], yx, um, thr, level=level)[0], want, (um, level, inner))

    def test_support_reads_y_then_x(self):
        ct = np.full((1, 120, 300), 50, np.uint8); ct[0, :, 160:164] = 120     # a sheet 10 px right of x = 150
        thr = self.p.papyrus_level(ct)
        self.assertGreater(self.p.end_support(ct, np.array([[400.0, 1200.0]]), 8.64, thr)[0], 0.4)   # (y 50, x 150)
        self.assertEqual(self.p.end_support(ct, np.array([[1200.0, 400.0]]), 8.64, thr)[0], 0.0)

    def test_rule_constants_are_read_when_called(self):
        """Changing a rule constant at run time changes what is computed, not only what the notes report."""
        p = self.p
        for name in ("END_RADIUS_MM", "END_SUPPORT", "END_RUN_MM", "CAP_MM", "AREA_FRAC"):
            self.addCleanup(setattr, p, name, getattr(p, name))
        ct, z, yx, um = _synthetic_scroll()
        hollow, thr = ct[-1:], p.papyrus_level(ct)            # no papyrus within 70 px (4.8 mm) of the centre
        self.assertEqual(p.end_support(hollow, yx[-1:], um, thr)[0], 0.0)
        h = p.window_origins(yx, um)[1]
        p.END_RADIUS_MM = 5.5
        self.assertEqual(p.end_support(hollow, yx[-1:], um, thr)[0], 1.0)
        self.assertGreater(p.window_origins(yx, um)[1], h)
        self.assertIn("within 5.5 mm", p._trim_note())
        sup, zz = np.r_[np.zeros(5), np.ones(6)], 64.0 * np.arange(11)
        self.assertTrue(p.trim_ends(np.ones(11, bool), sup, zz, um).any())       # 6 supported slices, a run needs 4
        p.END_RUN_MM = 4.0                                                        # now 8
        self.assertFalse(p.trim_ends(np.ones(11, bool), sup, zz, um).any())
        p.END_SUPPORT = 0.0
        self.assertTrue(p.trim_ends(np.ones(11, bool), sup, zz, um).all())
        area, zz = np.r_[np.full(30, 400.0), np.full(70, 1000.0)], 64.0 * np.arange(100)
        self.assertEqual(int(p.keep_band(area, zz, um).sum()), 100 - 12)          # 3 mm caps: 6 slices each end
        p.CAP_MM = 6.0
        self.assertEqual(int(p.keep_band(area, zz, um).sum()), 100 - 22)
        p.AREA_FRAC = 0.5
        self.assertEqual(int(p.keep_band(area, zz, um).sum()), 70 - 11)

    def test_trim_refuses_points_off_the_slice_heights(self):
        ct, z, yx, um = _synthetic_scroll()
        with tempfile.TemporaryDirectory() as d:
            np.savez(os.path.join(d, "S.npz"), ct=ct, z_l0=z, um=um, level=3, vol="S/volumes/1-8.640um-x")
            src = os.path.join(d, "src"); os.makedirs(src)
            with open(os.path.join(src, "S_umbilicus.json"), "w") as fh:
                json.dump(dict(control_points=[dict(x=1040, y=800, z=int(v) + 8, score=100) for v in z],
                               metadata=dict(voxelsize_um=um)), fh)
            with self.assertRaises(SystemExit):
                self.p.trim(src, d, os.path.join(d, "out"))
            self.assertEqual(self.p.trim(src, d, os.path.join(d, "band"), end_rule=False)["S"]["points"], 47)


class _PlaneReader:
    """slices.PlaneReader over a synthetic slice stack: level 3 holds ct[k] at plane 4 + 8k (level-0 z = 32 + 64k),
    level 5 its 4x subsample at plane 1 + 2k. Outside the stack reads as 0, like the bucket."""
    def __init__(self, ct, level):
        self.ct, self.level, self.missing = ct, level, 0
        f = 2 ** (level - 3)
        self.shape = [len(ct) * 8 // f, -(-ct.shape[1] // f), -(-ct.shape[2] // f)]
    def plane(self, z, y0=0, y1=None, x0=0, x1=None, threads=16):
        im = self.ct[(z - 4) // 8] if self.level == 3 else self.ct[(z - 1) // 2, ::4, ::4]
        assert (z - 4) % 8 == 0 if self.level == 3 else (z - 1) % 2 == 0
        y1 = self.shape[1] if y1 is None else y1; x1 = self.shape[2] if x1 is None else x1
        out = np.zeros((y1 - y0, x1 - x0), np.uint8)
        ya, yb, xa, xb = max(y0, 0), min(y1, im.shape[0]), max(x0, 0), min(x1, im.shape[1])
        if yb > ya and xb > xa:
            out[ya - y0:yb - y0, xa - x0:xb - x0] = im[ya:yb, xa:xb]
        return out


class EndcheckBucketTest(unittest.TestCase):
    """endcheck's bucket path (calibrate, and score or files without --data) on a synthetic scan served by a fake
    reader: the windows it reads are the pipeline's, so it gives the pipeline's answer; calibrate --radius."""
    def setUp(self):
        try:
            import scipy  # noqa: F401
            import endcheck
        except ImportError as e:
            self.skipTest(str(e))
        self.e = endcheck; self.ct, self.z, self.yx, self.um = _synthetic_scroll()
        self.vol = "S/volumes/1-8.640um-x"
        for patch in (mock.patch.object(endcheck.slices, "PlaneReader", lambda vol, level: _PlaneReader(self.ct, level)),
                      mock.patch.object(endcheck.slices, "LABELLED", ["S"]),
                      mock.patch.object(endcheck.slices, "truth", lambda s: (self.vol, self.T))):
            patch.start(); self.addCleanup(patch.stop)
        self.T = np.array([[self.z[12], *self.yx[0]], [self.z[-13], *self.yx[0]]])   # published over the body only

    def test_bucket_windows_are_the_pipeline_windows(self):
        p = self.e.pipeline
        with tempfile.TemporaryDirectory() as d:
            b = self.e.Bucket(self.vol, d, "S")
            np.testing.assert_array_equal(b.heights(), self.z)
            use = np.ones(len(self.z), bool)
            w, org = b.windows(self.z, self.yx, use)
            w0, org0 = p.centre_windows(self.ct, self.yx, self.um)
            np.testing.assert_array_equal(org, org0); np.testing.assert_array_equal(w, w0)
            keep = np.ones(len(self.z), bool)
            a = self.e._rule_bucket(b, self.z, self.yx, use, keep); c = p.end_trimmed_keep(self.ct, self.yx, self.z, self.um, keep)
            np.testing.assert_array_equal(a[0], c[0]); np.testing.assert_array_equal(a[1], c[1]); self.assertEqual(a[2], c[2])
            self.assertEqual(int(a[0].sum()), len(self.z) - 24)

    def test_calibrate_at_another_radius_restores_the_rule(self):
        p = self.e.pipeline; r0 = p.END_RADIUS_MM
        with tempfile.TemporaryDirectory() as d:
            a = self.e.calibrate(d)
            b = self.e.calibrate(d, radius_mm=5.5)
        self.assertEqual((a["rule"]["radius_mm"], b["rule"]["radius_mm"]), (r0, 5.5))
        self.assertEqual(p.END_RADIUS_MM, r0)
        A, B = a["scrolls"]["S"], b["scrolls"]["S"]
        self.assertEqual(A["end_rule"], len(self.z) - 24)           # broken and hollow ends dropped at 4 mm
        self.assertEqual(B["end_rule"] - A["end_rule"], 6)          # at 5.5 mm the hollow end up to the cap trim stays
        self.assertEqual(A["interior_below_bar"], 0)

    def test_missing_chunks_are_counted_from_the_cache_too(self):
        """A warm cache reports the absent chunk reads of the cold run, not 0; a cache file without a stored count
        gives None (unknown)."""
        class Counting(_PlaneReader):              # every plane read meets one absent chunk
            def plane(self, *a, **k):
                self.missing += 1
                return super().plane(*a, **k)
        use = np.ones(len(self.z), bool)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(self.e.slices, "PlaneReader", lambda vol, level: Counting(self.ct, level)):
            runs = []
            for _ in range(2):                     # cold, then warm
                b = self.e.Bucket(self.vol, d, "S"); b.area(self.z); b.windows(self.z, self.yx, use); b.windows(self.z, self.yx, use)
                runs.append(b.missing)
            self.assertEqual(runs, [3 * len(self.z)] * 2)   # one area read and two window reads per slice
            for f in os.listdir(d):
                p = os.path.join(d, f); arrays = dict(np.load(p)); arrays.pop("missing"); np.savez_compressed(p, **arrays)
            b = self.e.Bucket(self.vol, d, "S"); b.area(self.z); b.windows(self.z, self.yx, use)
            self.assertIsNone(b.missing)


@unittest.skipIf(torch is None, "numpy or torch unavailable")
class WiringTest(unittest.TestCase):
    def test_score_reproduces_collect_and_chain_collect(self):
        """endcheck.py score's pooled.all equals the run's result.json, for each stage; a folder with both stages is
        refused."""
        import shutil
        import pipeline, refine, endcheck
        ct, z, yx, um = _synthetic_scroll()
        n = len(z); T = np.array([[z[8], 800.0, 1040.0], [z[30], 820.0, 1030.0], [z[-9], 790.0, 1045.0]])
        present = np.ones(n, bool); present[:2] = False; ct = ct.copy(); ct[:2] = 0
        rng = np.random.default_rng(3)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pipeline.slices, "LABELLED", ["S"]), \
                mock.patch.object(pipeline.slices, "UNLABELLED", []), \
                mock.patch.object(pipeline.slices, "truth", lambda s: ("S/volumes/1-8.640um-x", T)):
            np.savez(os.path.join(d, "S.npz"), ct=ct, z_l0=z, um=um, level=3, vol="S/volumes/1-8.640um-x")
            F, Z = os.path.join(d, "F"), os.path.join(d, "Z"); os.makedirs(F); os.makedirs(Z)
            base = []
            for job in ("fold0s0", "fold0s1"):
                y = (yx + rng.normal(0, 25, yx.shape)).round(2); base.append(y)
                p = dict(z=z.tolist(), yx=y.tolist(), peak=[1.0] * n, present=present.tolist(), um=um, vol="S/volumes/1-8.640um-x")
                with open(os.path.join(F, f"{job}.json"), "w") as fh:
                    json.dump(dict(job=job, test=["S"], train_info={}, size=64, width=4, epochs=1, preds=dict(S=p)), fh)
            b = np.mean(base, 0); y2 = np.where(present[:, None], b + rng.normal(0, 10, b.shape), np.nan)
            p = dict(z=z.tolist(), base_yx=b.round(2).tolist(), yx=np.round(y2, 2).tolist(), peak=[1.0] * n,
                     present=present.tolist(), um=um, vol="S/volumes/1-8.640um-x")
            with open(os.path.join(Z, "refine_fold0.json"), "w") as fh:
                json.dump(dict(job="refine_fold0", test=["S"], train_info={}, base="F", preds=dict(S=p)), fh)
            first = pipeline.collect(d, F)["held_out_all"]["smoothed"]
            both = refine.chain_collect(d, Z)["held_out_all"]["chained"]
            self.assertNotEqual(first, both)
            self.assertEqual(endcheck.score(F, cache=os.path.join(d, "c"), data=d)["pooled"]["all"], first)
            self.assertEqual(endcheck.score(Z, cache=os.path.join(d, "c"), data=d)["pooled"]["all"], both)
            shutil.copy(os.path.join(Z, "refine_fold0.json"), F)
            with self.assertRaises(SystemExit):
                endcheck.score(F, cache=os.path.join(d, "c"), data=d)

    def test_predict_takes_only_its_own_scan_at_about_9_um(self):
        """--volume must match an existing slice file, and a scan outside 8 to 10 um is refused before any download."""
        import predict
        ct, z, yx, um = _synthetic_scroll(n=20, end=4)
        frame = predict.FRAME; predict.FRAME = 64; self.addCleanup(setattr, predict, "FRAME", frame)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(predict.slices, "extract_ranged", side_effect=AssertionError("no download expected")):
            np.savez(os.path.join(d, "S.npz"), ct=ct, z_l0=z, um=um, level=3, vol="S/volumes/1-8.640um-x")
            w = os.path.join(d, "w.pt"); torch.save(centrenet.Net(4).state_dict(), w)
            out = os.path.join(d, "out")
            with self.assertRaises(SystemExit):
                predict.predict("S", [w], [], d, out, vol="S/volumes/2-9.362um-y")         # another scan's slices
            with self.assertRaises(SystemExit):
                predict.predict("T", [w], [], d, out, vol="T/volumes/3-2.400um-0.2m")     # no T.npz: refused first
            np.savez(os.path.join(d, "U.npz"), ct=ct, z_l0=z, um=2.4, level=3, vol="U/volumes/3-2.400um-0.2m")
            with self.assertRaises(SystemExit):
                predict.predict("U", [w], [], d, out)
            self.assertFalse(os.path.exists(out) and os.listdir(out))
            r = predict.predict("S", [w], [], d, out, vol="S/volumes/1-8.640um-x/")
            with open(os.path.join(out, "S_umbilicus.json")) as fh:
                self.assertEqual(r["points"], len(json.load(fh)["control_points"]))

    def test_job_record_on_a_device_that_is_not_cuda(self):
        """pipeline.py job and refine.py chain write their record on a device without CUDA (cpu:0 stands in for mps)."""
        import pipeline, refine
        ct, z, yx, um = _synthetic_scroll(n=20, end=4)
        T = np.array([[z[2], *yx[0]], [z[-3], *yx[0]]])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pipeline.slices, "LABELLED", ["S"]), \
                mock.patch.object(pipeline.slices, "UNLABELLED", []), \
                mock.patch.object(pipeline.slices, "truth", lambda s: ("S/volumes/1-8.640um-x", T)), \
                mock.patch.object(centrenet, "train", lambda *a, **k: (centrenet.Net(2), {})), \
                mock.patch.object(refine, "train", lambda *a, **k: (centrenet.Net(2), {})):
            np.savez(os.path.join(d, "S.npz"), ct=ct, z_l0=z, um=um, level=3, vol="S/volumes/1-8.640um-x")
            pipeline.run_job("alls0", d, d, size=32, width=2, device="cpu:0")
            refine.chain_job("all", d, d, d, device="cpu:0")
            for f in ("alls0.json", "refine_all.json"):
                with open(os.path.join(d, f)) as fh:
                    rec = json.load(fh)
                self.assertEqual(rec["device"], "cpu:0"); self.assertNotIn("gpu", rec)

    def test_cv_weights_do_not_overwrite_chain_weights(self):
        """refine.py cv saves refine_cv_fold<k>.pt, so a cv run in a chain folder leaves chain's refine_fold<k>.pt."""
        import pipeline, refine
        ct, z, yx, um = _synthetic_scroll(n=20, end=4)
        T = np.array([[z[2], *yx[0]], [z[-3], *yx[0]]])
        side = refine.S; refine.S = 64; self.addCleanup(setattr, refine, "S", side)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pipeline, "FOLDS", [["S"], ["T"]]), \
                mock.patch.object(pipeline.slices, "LABELLED", ["S", "T"]), \
                mock.patch.object(pipeline.slices, "truth", lambda s: ("S/volumes/1-8.640um-x", T)), \
                mock.patch.object(refine, "train", lambda *a, **k: (centrenet.Net(2), {})):
            for s in ("S", "T"):
                np.savez(os.path.join(d, f"{s}.npz"), ct=ct, z_l0=z, um=um, level=3, vol=f"{s}/volumes/1-8.640um-x")
            with open(os.path.join(d, "refine_fold0.pt"), "wb") as fh:
                fh.write(b"chain weights")
            res = refine.cv(d, d, folds=(0,), offsets=(0.0,))
            self.assertIn("S", res["fold0"]["scrolls"])
            self.assertTrue(os.path.exists(os.path.join(d, "refine_cv_fold0.pt")))
            with open(os.path.join(d, "refine_fold0.pt"), "rb") as fh:
                self.assertEqual(fh.read(), b"chain weights")


@unittest.skipIf(np is None, "numpy unavailable")
class PlaneReaderTest(unittest.TestCase):
    """slices.PlaneReader and extract_ranged, the range reads predict.py and `slices.py extract` use, on a fake bucket:
    one zarr v2 level of raw 128^3 uint8 chunks with padded edge chunks and one absent chunk, served from a dict."""
    VOL = "S/volumes/1-9.362um-1.2m-x.zarr"

    def setUp(self):
        import slices
        self.slices = slices
        rng = np.random.default_rng(0); C = 128; self.shape = shape = (300, 290, 270)
        vol = rng.integers(1, 256, shape).astype(np.uint8)
        self.store = {f"{self.VOL}/3/.zarray": json.dumps({"shape": list(shape), "chunks": [C] * 3, "dtype": "|u1",
                      "compressor": None, "fill_value": 0, "order": "C", "dimension_separator": "/"}).encode()}
        for cz in range(3):
            for cy in range(3):
                for cx in range(3):
                    if (cz, cy, cx) == (1, 1, 0):
                        vol[C:2 * C, C:2 * C, :C] = 0; continue          # absent chunk reads as 0
                    blk = np.zeros((C, C, C), np.uint8); sub = vol[cz * C:(cz + 1) * C, cy * C:(cy + 1) * C, cx * C:(cx + 1) * C]
                    blk[:sub.shape[0], :sub.shape[1], :sub.shape[2]] = sub
                    self.store[f"{self.VOL}/3/{cz}/{cy}/{cx}"] = blk.tobytes()
        self.vol = vol
        key = lambda url: url[len(slices.B):]
        def get(url, retries=6):
            return self.store.get(key(url))
        def get_range(url, lo, hi, retries=6):
            b = self.store.get(key(url)); return None if b is None else b[lo:hi + 1]
        for p in (mock.patch.object(slices, "get", get), mock.patch.object(slices, "get_range", get_range),
                  mock.patch.object(slices, "volume", lambda s: self.VOL)):
            p.start(); self.addCleanup(p.stop)

    def test_windows_match_the_volume_with_edges_outside_and_absent_chunks(self):
        r = self.slices.PlaneReader(self.VOL, 3); rng = np.random.default_rng(1); Z, H, W = self.shape
        for _ in range(200):
            z = int(rng.integers(-5, Z + 5)); y0 = int(rng.integers(-60, H)); x0 = int(rng.integers(-60, W))
            y1 = y0 + int(rng.integers(1, 200)); x1 = x0 + int(rng.integers(1, 200))
            exp = np.zeros((y1 - y0, x1 - x0), np.uint8)
            ya, yb, xa, xb = max(0, y0), min(H, y1), max(0, x0), min(W, x1)
            if 0 <= z < Z and ya < yb and xa < xb:
                exp[ya - y0:yb - y0, xa - x0:xb - x0] = self.vol[z, ya:yb, xa:xb]
            np.testing.assert_array_equal(r.plane(z, y0, y1, x0, x1), exp)
        self.assertGreater(r.missing, 0)

    def test_absent_chunks_are_counted_across_threads(self):
        r = self.slices.PlaneReader(self.VOL, 3)
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda z: r.plane(z, threads=4), range(128, 256)))   # each whole plane meets the absent chunk
        self.assertEqual(r.missing, 128)

    def test_extract_ranged_writes_every_8th_plane_at_level0_heights(self):
        with tempfile.TemporaryDirectory() as d:
            npz = np.load(self.slices.extract_ranged("S", os.path.join(d, "S.npz")))
            np.testing.assert_array_equal(npz["ct"], self.vol[4::8])
            np.testing.assert_array_equal(npz["z_l0"], np.arange(4, self.shape[0], 8) * 8)
            self.assertEqual((float(npz["um"]), int(npz["level"]), str(npz["vol"])), (9.362, 3, self.VOL))

    def test_extract_and_extract_ranged_write_the_same_file(self):
        """extract (whole chunks, the reader the training slices came from) and extract_ranged agree."""
        try:
            import numcodecs  # noqa: F401  (slices.Arr imports it)
        except ImportError:
            self.skipTest("numcodecs unavailable")
        with tempfile.TemporaryDirectory() as d:
            a = np.load(self.slices.extract("S", os.path.join(d, "a.npz")))
            b = np.load(self.slices.extract_ranged("S", os.path.join(d, "b.npz")))
            for k in ("ct", "z_l0", "um", "level", "vol"):
                np.testing.assert_array_equal(a[k], b[k])


if __name__ == "__main__":
    unittest.main()
