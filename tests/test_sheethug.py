"""Tests for kit.sheethug (fused-contact sheet stacks, two-scale net, split-recall score)"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

import numpy as np

HAVE_SCIPY = importlib.util.find_spec("scipy") is not None
HAVE_SKIMAGE = importlib.util.find_spec("skimage") is not None
HAVE_TORCH = importlib.util.find_spec("torch") is not None
HAVE_SS = (importlib.util.find_spec("synthetic_slices") is not None
           and importlib.util.find_spec("cv2") is not None)
SMALL = (48, 96, 96)


@unittest.skipUnless(HAVE_SCIPY, "needs scipy")
class TestStack(unittest.TestCase):
    def setUp(self):
        from kit import sheethug
        self.H = sheethug

    def test_same_seed_same_block_and_sub_box_matches(self):
        H = self.H
        st = H.Stack(5, SMALL)
        a = st.raster()
        b = H.Stack(5, SMALL).raster()
        self.assertTrue(np.array_equal(a["owner"], b["owner"]))
        sub = st.raster(origin=(8, 16, 24), shape=(16, 32, 32))
        self.assertTrue(np.array_equal(sub["owner"], a["owner"][8:24, 16:48, 24:56]))
        self.assertTrue(np.array_equal(sub["centre"], a["centre"][8:24, 16:48, 24:56]))

    def test_sheets_are_ordered_and_apart_gaps_kept(self):
        H = self.H
        for seed in range(6):
            st = H.Stack(seed, SMALL)
            sep = st.H[1:] - st.H[:-1] - (st.T[1:] + st.T[:-1]) / 2
            apart = st.P < 1e-6
            if apart.any():
                self.assertGreaterEqual(float(sep[apart].min()), H.GAP_MIN - 1e-4)
            self.assertTrue(np.all(st.H[1:] > st.H[:-1]))

    def test_fused_islands_touch_with_no_gap(self):
        H = self.H
        found = False
        for seed in range(12):
            st = H.Stack(seed, SMALL)
            full = st.P > 0.999
            if full.any():
                sep = (st.H[1:] - st.H[:-1] - (st.T[1:] + st.T[:-1]) / 2)[full]
                self.assertLessEqual(float(sep.max()), 1e-3)
                found = True
        self.assertTrue(found, "no fully fused pair in 12 seeds")

    def test_centre_inside_papyrus_and_interface_only_between_sheets(self):
        H = self.H
        b = H.block(3, SMALL)
        self.assertTrue(np.all(b["owner"][b["centre"]] > 0))
        self.assertTrue(np.all(b["owner"][b["interface"]] > 0))
        self.assertEqual(b["ct"].dtype, np.uint8)
        pap = b["ct"][b["owner"] > 0].mean()
        gap = b["ct"][b["owner"] == 0].mean()
        self.assertGreater(pap, gap)

    def test_context_box_is_centred_and_padded(self):
        H = self.H
        ct = np.zeros((64, 64, 64), np.uint8)
        ct[30:34, 30:34, 30:34] = 255
        P = H.pooled(ct)
        self.assertEqual(P.shape, (2, 16, 16, 16))
        cx = H.context_box(P, (32, 32, 32))
        n = H.CONTEXT // H.CTX_DS
        self.assertEqual(cx.shape, (2, n, n, n))
        # the bright cube sits at the box centre; cells outside the volume have share 0
        z, y, x = np.unravel_index(int(np.argmax(cx[0])), cx[0].shape)
        self.assertTrue(abs(z - n // 2) <= 1 and abs(y - n // 2) <= 1 and abs(x - n // 2) <= 1)
        self.assertEqual(float(cx[1, 0, 0, 0]), 0.0)
        self.assertEqual(float(cx[1, n // 2, n // 2, n // 2]), 1.0)
        with self.assertRaises(H.HugError):
            H.context_box(P, (33, 32, 32))


@unittest.skipUnless(HAVE_SCIPY and HAVE_SKIMAGE, "needs scipy and scikit-image")
class TestScore(unittest.TestCase):
    def setUp(self):
        from kit import sheethug
        self.H = sheethug

    def pair(self):
        # two touching vertical sheets, 4 px wide each, ids 1 and 2
        o = np.zeros((64, 64), np.uint8)
        o[:, 20:24] = 1
        o[:, 24:28] = 2
        return o

    def test_contact_zone_and_truth_lines_keep_two_sheets(self):
        H = self.H
        o = self.pair()
        cz = H.contact_zone(o)
        self.assertTrue(cz[:, 22:26].all())
        lines = H.truth_lines(o)
        self.assertTrue(lines[:, 20:24].any() and lines[:, 24:28].any())

    def test_split_recall_punishes_a_merged_line(self):
        H = self.H
        o = self.pair()
        lines = H.truth_lines(o)
        mask = np.ones(o.shape, bool)
        good = H.split_counts(lines, lines, o, mask, tol=2)
        merged = np.zeros(o.shape, bool)
        merged[:, 24] = True
        bad = H.split_counts(merged, lines, o, mask, tol=2)
        self.assertEqual(good["tp_s"], good["n_r"])
        self.assertLess(bad["tp_s"], 0.7 * bad["n_r"])
        self.assertLessEqual(bad["tp_s"], bad["tp_r"])

    def test_split_recall_assigns_each_predicted_pixel_to_its_nearest_sheet(self):
        H = self.H
        # sheet 1's line: column 10, rows 0 to 31; sheet 2's line: column 13, rows 0 to 15 (3 px apart, so a
        # predicted pixel between them lies within 2 px of both)
        o = np.zeros((32, 32), np.uint8)
        o[:, 10] = 1
        o[:16, 13] = 2
        ref = o > 0
        mask = np.ones(o.shape, bool)
        # a full-height line at column 11 is nearer sheet 1 everywhere: plain recall credits both sheets, split
        # recall only sheet 1's 32 pixels
        pred = np.zeros(o.shape, bool)
        pred[:, 11] = True
        c = H.split_counts(pred, ref, o, mask, tol=2)
        self.assertEqual((c["n_r"], c["tp_r"], c["tp_s"]), (48, 48, 32))
        # rows 0 to 15 of column 12 are nearer sheet 2: plain recall credits 32 pixels on both sheets, split recall
        # only sheet 2's 16 (an assignment that ignored the nearest sheet would give 32)
        pred = np.zeros(o.shape, bool)
        pred[:16, 12] = True
        c = H.split_counts(pred, ref, o, mask, tol=2)
        self.assertEqual((c["n_r"], c["tp_r"], c["tp_s"]), (48, 32, 16))
        # one predicted line on each sheet recovers both
        pred = np.zeros(o.shape, bool)
        pred[:, 10] = True
        pred[:16, 13] = True
        self.assertEqual(H.split_counts(pred, ref, o, mask, tol=2)["tp_s"], 48)
        # a truth pixel outside MASK is not counted, and a predicted pixel outside MASK recalls nothing
        m2 = mask.copy()
        m2[:, 12:] = False
        pred = np.zeros(o.shape, bool)
        pred[:16, 13] = True
        c = H.split_counts(pred, ref, o, m2, tol=2)
        self.assertEqual((c["n_r"], c["n_p"], c["tp_s"]), (32, 0, 0))

    @unittest.skipUnless(HAVE_SS, "needs synthetic_slices")
    def test_nonfinite_map_is_refused(self):
        H = self.H
        m = np.zeros((32, 32), np.float32)
        m[3, 3] = np.nan
        with self.assertRaises(H.HugError):
            H.nms_lines(m, np.ones((32, 32), bool))


@unittest.skipUnless(HAVE_SCIPY and HAVE_TORCH, "needs scipy and torch")
class TestNet(unittest.TestCase):
    def test_forward_shapes_and_local_arm_ignores_context(self):
        import torch
        from kit import sheethug as H
        torch.manual_seed(0)
        net = H.make_net(8).eval()
        n = H.CONTEXT // H.CTX_DS
        x = torch.rand(1, 1, H.LOCAL, H.LOCAL, H.LOCAL)
        with torch.no_grad():
            y0 = net(x, torch.zeros(1, 2, n, n, n))
            y1 = net(x, torch.rand(1, 2, n, n, n))
        self.assertEqual(tuple(y0.shape), (1, len(H.OUTS), H.LOCAL, H.LOCAL, H.LOCAL))
        self.assertTrue(torch.isfinite(y0).all())
        self.assertGreater(float((y0 - y1).abs().max()), 0.0)

    def test_sampler_arms(self):
        from kit import sheethug as H
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "block-1-0000.npz")
            H.save_block(H.block(1, (96, 96, 96)), p)
            for arm in ("wide", "local"):
                x, cx, y = H.Sampler([p], arm, 1).batch(2)
                self.assertEqual(x.shape, (2, 1, H.LOCAL, H.LOCAL, H.LOCAL))
                self.assertEqual(y.shape, (2, 3, H.LOCAL, H.LOCAL, H.LOCAL))
                if arm == "local":
                    self.assertEqual(float(np.abs(cx).max()), 0.0)
                else:
                    self.assertGreater(float(cx[:, 1].max()), 0.0)
            with self.assertRaises(H.HugError):
                H.Sampler([p], "both", 1)


@unittest.skipUnless(HAVE_SCIPY and HAVE_SKIMAGE and HAVE_TORCH and HAVE_SS, "needs scipy, scikit-image, torch and synthetic_slices")
class TestGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from kit import sheethug as H
        cls.H = H
        cls.d = tempfile.TemporaryDirectory()
        cls.block = os.path.join(cls.d.name, "block-1-0000.npz")
        H.save_block(H.block(1, (40, 96, 96)), cls.block)  # seed 1 has about 680 contact line pixels
        cls.w = []
        for seed in (1, 2):
            torch.manual_seed(seed)
            net = H.make_net(8).eval()
            path = os.path.join(cls.d.name, f"wide-s{seed}.pt")
            H.save_net(net, {"arm": "wide", "seed": seed, "width": 8}, path)
            cls.w.append(path)

    @classmethod
    def tearDownClass(cls):
        cls.d.cleanup()

    def manual(self, maps_of):
        """Counts pooled over the gate's slices for maps given by maps_of(block, z)."""
        H = self.H
        b = H.load_block(self.block)
        Z, Y, X = b["ct"].shape
        foot = np.zeros((Y, X), bool)
        foot[H.SLICE_MARGIN:-H.SLICE_MARGIN, H.SLICE_MARGIN:-H.SLICE_MARGIN] = True
        return H.pool([H.slice_eval(maps_of(b, z), b["owner"][z], foot) for z in H.axial_slices(Z)])

    def test_gate_names_controls_and_maps(self):
        H = self.H
        msgs = []
        res = H.gate([self.block], self.w, "cpu", progress=msgs.append)
        self.assertEqual(set(res), {"wide-s1.pt", "wide-s2.pt", "ridge-sato", "control-oracle", "control-merged",
                                    "control-flip"})
        self.assertEqual(msgs, ["PROGRESS 1/1 block-1-0000.npz"])
        self.assertEqual((res["wide-s2.pt"]["arm"], res["wide-s2.pt"]["seed"]), ("wide", 2))
        self.assertEqual(res["control-oracle"]["arm"], "control-oracle")
        self.assertGreater(res["control-oracle"]["zones"]["contact"]["split_f1"], 0.95)
        self.assertLess(res["control-merged"]["zones"]["contact"]["split_recall"],
                        res["control-oracle"]["zones"]["contact"]["split_recall"] - 0.2)
        rid = self.manual(lambda b, z: H.ridge_map(b["ct"][z].astype(np.float32) / 255.0))
        self.assertEqual(res["ridge-sato"]["zones"], rid)
        net, meta = H.load_net(self.w[0])
        prob = H.predict(net, H.load_block(self.block)["ct"], "wide")[1]
        flip = self.manual(lambda b, z: np.ascontiguousarray(prob[z][:, ::-1]))
        self.assertEqual(res["control-flip"]["zones"], flip)
        own = self.manual(lambda b, z: prob[z])
        self.assertEqual(res["wide-s1.pt"]["zones"], own)
        merged = self.manual(lambda b, z: H.control_probs(b["owner"][z])["merged"])
        self.assertEqual(res["control-merged"]["zones"], merged)
        self.assertGreater(merged["all"]["precision"], 0.5)

    def test_gate_without_ridge_and_non_finite(self):
        H = self.H
        res = H.gate([self.block], self.w[:1], "cpu", progress=None, ridge=False)
        self.assertNotIn("ridge-sato", res)
        orig = H.predict
        try:
            H.predict = lambda *a, **k: np.full((3,) + H.load_block(self.block)["ct"].shape, np.nan, np.float32)
            with self.assertRaisesRegex(H.HugError, "non-finite probabilities"):
                H.gate([self.block], self.w[:1], "cpu", progress=None)
        finally:
            H.predict = orig

    def test_merged_control_is_the_papyrus_skeleton(self):
        H = self.H
        o = np.zeros((32, 32), np.uint8)
        o[:, 10:14] = 1
        o[:, 14:18] = 2
        cp = H.control_probs(o)
        self.assertEqual(int(cp["merged"][:, :9].sum() + cp["merged"][:, 19:].sum()), 0)
        self.assertGreater(int(cp["merged"].sum()), 0)
        cols = np.nonzero(cp["merged"])[1]
        self.assertLessEqual(abs(float(cols.mean()) - 13.5), 0.6)  # one line through both sheets' middle
        self.assertEqual(cp["oracle"].dtype, np.float32)


if __name__ == "__main__":
    unittest.main()
