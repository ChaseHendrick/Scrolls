"""scripts/segzoo/: the SS2D selective scan, network builders, nnU-Net trainers, the SAM 2 sheet follower and the
frozen-feature probe. Each class skips when its package (torch, monai, transformers, nnunetv2) is missing."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None
try:
    import torch
except ImportError:
    torch = None

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "scripts" / "segzoo"
HAVE_MONAI = torch is not None and importlib.util.find_spec("monai") is not None
HAVE_TF = torch is not None and importlib.util.find_spec("transformers") is not None
HAVE_NNUNET = torch is not None and importlib.util.find_spec("nnunetv2") is not None
NAMES = ("segzoo_ss2d", "segzoo_nets", "segzoo_nnunet", "segzoo_sam2", "segzoo_probe")


def setUpModule():
    sys.path.insert(0, str(FOLDER))


def tearDownModule():
    if str(FOLDER) in sys.path:
        sys.path.remove(str(FOLDER))
    for n in NAMES:
        sys.modules.pop(n, None)


@unittest.skipIf(torch is None, "needs torch")
class SelectiveScanTest(unittest.TestCase):
    def setUp(self):
        import segzoo_ss2d
        self.m = segzoo_ss2d
        torch.manual_seed(0)

    def inputs(self, b=2, d=8, L=29, N=4, g=2):
        return (torch.randn(b, d, L, requires_grad=True), torch.randn(b, d, L), -torch.rand(d, N) * 3,
                torch.randn(b, g, N, L), torch.randn(b, g, N, L), torch.randn(d), torch.randn(d))

    def test_chunked_scan_equals_the_step_by_step_loop(self):
        u, dl, A, B, C, D, bias = self.inputs()
        ref = self.m.selective_scan_ref(u, dl, A, B, C, D, bias)
        for chunk in (1, 4, 16, 64):
            y = self.m.selective_scan(u, dl, A, B, C, D, bias, chunk=chunk)
            self.assertLess((y - ref).abs().max().item(), 1e-4, chunk)

    def test_gradients_match_the_loop(self):
        u, dl, A, B, C, D, bias = self.inputs()
        g_ref = torch.autograd.grad(self.m.selective_scan_ref(u, dl, A, B, C, D, bias).sum(), u)[0]
        g = torch.autograd.grad(self.m.selective_scan(u, dl, A, B, C, D, bias, chunk=5).sum(), u)[0]
        self.assertLess((g - g_ref).abs().max().item(), 1e-4)

    def test_long_sequences_do_not_overflow(self):
        u, dl, A, B, C, D, bias = self.inputs(L=600)
        y = self.m.selective_scan(u, dl * 5, A * 10, B, C, D, bias)
        self.assertTrue(torch.isfinite(y).all())

    def test_bad_shapes_are_refused(self):
        u, dl, A, B, C, D, bias = self.inputs()
        with self.assertRaises(ValueError):
            self.m.selective_scan(u, dl[:, :, :-1], A, B, C)
        with self.assertRaises(ValueError):
            self.m.selective_scan(u, dl, A[:-1], B, C)
        with self.assertRaises(ValueError):
            self.m.selective_scan(u, dl, A, B[:, :1].repeat(1, 3, 1, 1), C[:, :1].repeat(1, 3, 1, 1))
        with self.assertRaises(ValueError):
            self.m.selective_scan(u, dl, A, B, C, chunk=0)

    def test_scan_orders_fold_back(self):
        x = torch.arange(2 * 3 * 4 * 5, dtype=torch.float32).reshape(2, 3, 4, 5)
        xs = self.m.SS2D.scan_orders(x)
        self.assertEqual(tuple(xs.shape), (2, 4, 3, 20))
        self.assertTrue(torch.equal(xs[:, 1, :, :4], x[:, :, :, 0]))
        self.assertTrue(torch.allclose(self.m.SS2D.merge_orders(xs, 4, 5), 4 * x.reshape(2, 3, 20)))

    def test_unet_shapes_and_backward(self):
        net = self.m.SS2DUNet(2, 3, widths=(8, 16, 32))
        y = net(torch.randn(1, 2, 16, 24))
        self.assertEqual(tuple(y.shape), (1, 3, 16, 24))
        y.mean().backward()
        self.assertTrue(all(p.grad is not None for p in net.parameters() if p.requires_grad))
        with self.assertRaisesRegex(ValueError, "divisible by 4"):
            net(torch.randn(1, 2, 18, 24))


@unittest.skipIf(not (HAVE_MONAI and HAVE_TF), "needs torch, monai and transformers")
class BuildTest(unittest.TestCase):
    def test_every_name_builds_and_keeps_the_input_size(self):
        import segzoo_nets
        cases = {"mednext-s": (3, (1, 1, 32, 32, 32)), "mednext-b": (2, (1, 3, 32, 32)),
                 "swinunetr-v2": (2, (2, 1, 64, 64)), "segresnet": (3, (1, 1, 16, 16, 16)),
                 "segformer-b0": (2, (1, 17, 64, 64)), "ss2dunet": (2, (1, 1, 32, 32))}
        for name, (dims, shape) in cases.items():
            kw = {"widths": (8, 16, 32)} if name == "ss2dunet" else {}
            net = segzoo_nets.build(name, shape[1], 4, dims=dims, **kw)
            with torch.no_grad():
                y = net(torch.randn(*shape))
            self.assertEqual(tuple(y.shape), (shape[0], 4) + shape[2:], name)
        self.assertEqual(set(cases) - set(segzoo_nets.names()), set())

    def test_refusals(self):
        import segzoo_nets
        with self.assertRaisesRegex(ValueError, "unknown network"):
            segzoo_nets.build("resnet", 1, 2)
        with self.assertRaisesRegex(ValueError, "2D only"):
            segzoo_nets.build("segformer-b0", 1, 2, dims=3)
        with self.assertRaisesRegex(ValueError, "2D only"):
            segzoo_nets.build("ss2dunet", 1, 2, dims=3)
        with self.assertRaisesRegex(ValueError, "dims"):
            segzoo_nets.build("mednext-s", 1, 2, dims=4)


@unittest.skipIf(not (HAVE_NNUNET and HAVE_MONAI and HAVE_TF), "needs torch, nnunetv2, monai and transformers")
class TrainerTest(unittest.TestCase):
    class Config:
        def __init__(self, patch):
            self.patch_size = patch

    def test_trainers_build_their_network_from_the_plans(self):
        import segzoo_nnunet
        t = segzoo_nnunet.TRAINERS
        net = t["nnUNetTrainer_SZMedNeXtS"].build_network_architecture(None, self.Config([32, 32, 32]), 1, 3, True)
        with torch.no_grad():
            self.assertEqual(tuple(net(torch.randn(1, 1, 32, 32, 32)).shape), (1, 3, 32, 32, 32))
        net = t["nnUNetTrainer_SZSS2D"].build_network_architecture(None, self.Config([32, 32]), 1, 2)
        self.assertEqual(type(net).__name__, "SS2DUNet")
        with self.assertRaisesRegex(RuntimeError, "no 3D form"):
            t["nnUNetTrainer_SZSegFormerB2"].build_network_architecture(None, self.Config([64, 64, 64]), 1, 2)
        with self.assertRaisesRegex(RuntimeError, "divisible by 32"):
            t["nnUNetTrainer_SZSwinUNETR"].build_network_architecture(None, self.Config([48, 48, 48]), 1, 2)

    def test_every_trainer_is_an_nnunet_trainer_with_one_network(self):
        import segzoo_nnunet
        from nnunetv2.training.nnUNetTrainer.nnUNetTrainer import nnUNetTrainer
        import segzoo_nets
        for name, cls in segzoo_nnunet.TRAINERS.items():
            self.assertTrue(issubclass(cls, nnUNetTrainer), name)
            self.assertTrue(name.startswith("nnUNetTrainer_SZ"), name)
            self.assertIn(cls.NET, segzoo_nets.names(), name)

    def test_shim_imports_every_trainer(self):
        import segzoo_nnunet
        with tempfile.TemporaryDirectory() as tmp:
            path = segzoo_nnunet.write_shim(tmp)
            ns = {}
            exec(compile(path.read_text(), str(path), "exec"), ns)
            for name in segzoo_nnunet.TRAINERS:
                self.assertIn(name, ns)


class FakePredictor:
    """Stands in for a SAM 2 video predictor: every frame returns the prompt's box filled in, shifted one pixel
    down per frame away from the key, so the follow drifts like a tilted sheet."""

    def __init__(self, n, H, W):
        self.n, self.H, self.W = n, H, W

    def init_state(self, video_path=None, *args):
        frames = sorted(Path(video_path).glob("*.jpg")) if video_path else None
        if video_path is not None:
            assert len(frames) == self.n
        return {"prompts": {}}

    def reset_state(self, state):
        state["prompts"] = {}

    def add_new_points_or_box(self, state, frame_idx, obj_id, box=None, points=None, labels=None):
        state["prompts"][obj_id] = (frame_idx, [int(v) for v in box])

    def add_new_mask(self, state, frame_idx, obj_id, mask):
        ys, xs = np.nonzero(mask)
        state["prompts"][obj_id] = (frame_idx, [xs.min(), ys.min(), xs.max(), ys.max()])

    def propagate_in_video(self, state, start_frame_idx=0, reverse=False):
        frames = range(start_frame_idx, -1, -1) if reverse else range(start_frame_idx, self.n)
        for f in frames:
            ids = sorted(state["prompts"])
            out = np.full((len(ids), 1, self.H, self.W), -5.0, np.float32)
            for j, oid in enumerate(ids):
                key, (x0, y0, x1, y1) = state["prompts"][oid]
                s = abs(f - key)
                out[j, 0, max(0, y0 + s):min(self.H, y1 + s + 1), x0:x1 + 1] = 5.0
            yield f, ids, out


@unittest.skipIf(np is None, "needs numpy")
class SheetFollowTest(unittest.TestCase):
    def setUp(self):
        import segzoo_sam2
        self.m = segzoo_sam2

    def truth(self, n=9, H=24, W=10):
        t = np.zeros((n, H, W), np.uint16)
        for f in range(n):
            t[f, 4:6] = 1                       # two flat sheets, two empty rows apart
            t[f, 8:10] = 2
        return t

    def test_follow_and_score_with_a_stand_in_predictor(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("needs Pillow")
        truth = self.truth()
        seed = truth[4].astype(np.int32)
        cube = truth.astype(np.float32) + 0.1
        labels, info = self.m.follow(FakePredictor(*truth.shape), cube, seed, key=4)
        self.assertEqual(labels.shape, truth.shape)
        self.assertEqual(info["objects"], [1, 2])
        res = self.m.score(labels, truth, seed, key=4)
        self.assertEqual(set(res["objects"]), {"1", "2"})
        self.assertEqual(res["objects"]["1"]["sheet"], 1)
        self.assertEqual(res["objects"]["1"]["first_hop"], 3)          # the stand-in sinks onto sheet 2
        self.assertLess(res["objects"]["1"]["identity_kept"], 1.0)
        self.assertEqual(res["control"]["1"]["identity_kept"], 1.0)    # flat sheets: the copy control is perfect
        self.assertFalse(res["beats_control"])

    def test_score_finds_a_hop(self):
        truth = self.truth()
        seed = truth[4].astype(np.int32)
        pred = np.zeros_like(truth)
        pred[:, 8:10] = 2
        pred[:6, 4:6] = 1
        pred[6:, 8:10] = 1       # object 1 jumps onto sheet 2 two slices after the key
        res = self.m.score(pred, truth, seed, key=4)
        self.assertEqual(res["objects"]["1"]["first_hop"], 2)
        self.assertEqual(res["objects"]["2"]["identity_kept"], 1.0)

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "no labeled pixel"):
            self.m.seed_objects(np.zeros((4, 4)))
        with self.assertRaisesRegex(ValueError, "2D"):
            self.m.seed_objects(np.zeros((2, 4, 4)))
        with self.assertRaisesRegex(ValueError, "outside"):
            self.m.follow(FakePredictor(3, 4, 4), np.zeros((3, 4, 4)), np.ones((4, 4), int), key=5)
        self.assertIsNone(self.m.box_of(np.zeros((3, 3), bool)))
        self.assertEqual(self.m.box_of(np.eye(3, dtype=bool)), [0, 0, 2, 2])

    def test_uint8_window_is_shared_by_all_slices(self):
        cube = np.stack([np.full((4, 4), 1.0), np.full((4, 4), 3.0)])
        u = self.m.to_uint8(cube, 0, 100)
        self.assertEqual(int(u[0].max()), 0)
        self.assertEqual(int(u[1].min()), 255)


@unittest.skipIf(torch is None or np is None, "needs torch and numpy")
class ProbeTest(unittest.TestCase):
    def setUp(self):
        import segzoo_probe
        self.m = segzoo_probe

    def data(self, n, seed, shift=3.0):
        rng = np.random.default_rng(seed)
        y = rng.integers(0, 3, n)
        X = rng.normal(0, 1, (n, 6))
        X[np.arange(n), y] += shift
        return {"features": X, "labels": np.array(["abc"[i] for i in y]),
                "groups": np.array([f"g{i % 4}" for i in range(n)]), "ids": np.array([f"i{i}" for i in range(n)])}

    def test_head_learns_separable_classes_and_the_control_does_not(self):
        res = self.m.run_fit(self.data(120, 0), self.data(60, 1))
        self.assertGreater(res["accuracy"], 0.9)
        self.assertLess(res["control_shuffled_labels"]["mean"], 0.6)
        self.assertLessEqual(res["low"], res["accuracy"])
        self.assertEqual(len(res["hits"]), 60)

    def test_paired_comparison_against_another_method(self):
        test = self.data(60, 1)
        other = {"name": "always wrong", "hits": {str(i): 0 for i in test["ids"]}}
        res = self.m.run_fit(self.data(120, 0), test, against=other)
        self.assertEqual(res["paired_against"]["verdict"], "better")
        with self.assertRaisesRegex(ValueError, "lacks"):
            self.m.run_fit(self.data(120, 0), test, against={"hits": {}})

    def test_unseen_test_labels_are_refused(self):
        test = self.data(10, 1)
        test["labels"] = np.array(["z"] * 10)
        with self.assertRaisesRegex(ValueError, "never seen"):
            self.m.run_fit(self.data(30, 0), test)

    def test_image_range_check(self):
        self.assertEqual(self.m.as_float_images(np.full((1, 2, 2), 255, np.uint8)).max(), 1.0)
        with self.assertRaises(ValueError):
            self.m.as_float_images(np.full((1, 2, 2), 3.0))

    def test_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, seed, n in (("tr", 0, 90), ("te", 1, 30)):
                np.savez(Path(tmp) / f"{name}.npz", **self.data(n, seed))
            out = Path(tmp) / "r.json"
            code = self.m.main(["fit", str(Path(tmp) / "tr.npz"), str(Path(tmp) / "te.npz"), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.read_text())["n_test"], 30)


if __name__ == "__main__":
    unittest.main()
