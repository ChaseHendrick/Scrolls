"""kit mpsparity: the CPU-versus-MPS check passes when two devices agree, fails when they do not, is VOID when its
control cannot fail; the built-in networks build and pass on the CPU; a network from your own script runs."""
import importlib.util
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

HAVE_TORCH = importlib.util.find_spec("torch") is not None

if HAVE_TORCH:
    import torch
    from kit import mpsparity as M


class Tiny(torch.nn.Module if HAVE_TORCH else object):
    def __init__(self):
        super().__init__()
        self.c = torch.nn.Conv3d(1, 4, 3, padding=1)
        self.n = torch.nn.GroupNorm(2, 4)
        self.h = torch.nn.Conv3d(4, 1, 1)

    def forward(self, x):
        return self.h(torch.relu(self.n(self.c(x))))


class Blind(torch.nn.Module if HAVE_TORCH else object):
    """Output that ignores its input: the depth-reversal control cannot fail, so the check must be VOID."""
    def __init__(self):
        super().__init__()
        self.b = torch.nn.Parameter(torch.randn(1, 1, 4, 4, 4))

    def forward(self, x):
        return self.b.expand(x.shape[0], -1, -1, -1, -1) + 0 * x.mean()


def noisy(net):
    with torch.no_grad():
        for p in net.parameters():
            p.add_(0.05 * torch.randn_like(p))


SHAPE = (2, 1, 8, 8, 8)


@unittest.skipUnless(HAVE_TORCH, "torch not installed")
class Checks(unittest.TestCase):
    def test_same_device_passes_every_check(self):
        for fn in (M.forward_check, M.grad_check, M.train_check):
            r = fn(Tiny, SHAPE, "cpu", "cpu", seed=3)
            self.assertEqual(r["outcome"], "PASS", r)
            self.assertEqual(r["value"], 0.0)
            self.assertGreaterEqual(r["control"], M.CONTROL_FACTOR * r["tol"])

    def test_a_different_device_copy_fails(self):
        for fn in (M.forward_check, M.grad_check, M.train_check):
            r = fn(Tiny, SHAPE, "cpu", "cpu", seed=3, mutate_dev=noisy)
            self.assertEqual(r["outcome"], "FAIL", r)
            self.assertGreater(r["value"], r["tol"])

    def test_control_that_cannot_fail_is_void(self):
        r = M.forward_check(Blind, (2, 1, 4, 4, 4), "cpu", "cpu", seed=1)
        self.assertEqual(r["outcome"], "VOID", r)

    def test_train_reports_loss_curves(self):
        r = M.train_check(Tiny, SHAPE, "cpu", "cpu", seed=0, steps=3)
        self.assertEqual(len(r["loss_ref"]), 3)
        self.assertEqual(r["loss_ref"], r["loss_dev"])
        self.assertEqual(r["loss_max_rel_diff"], 0.0)

    def test_dropout_is_switched_off_for_grad_and_train(self):
        net = M.no_dropout(torch.nn.Sequential(torch.nn.Dropout(0.3), torch.nn.Linear(2, 2)))
        self.assertEqual(net[0].p, 0.0)

    def test_ops_on_cpu(self):
        r = M.ops("cpu")
        self.assertTrue(r["ok"], r)
        self.assertIn("grid_sample_3d_bilinear", r["ops"])

    def test_bench_batch_and_memory_cap(self):
        r = M.bench(Tiny, (8, 1, 8, 8, 8), "cpu", 1, batch=2)
        self.assertEqual(r["batch_shape"][0], 2)
        self.assertAlmostEqual(r["s_per_sample"], r["s_per_step"] / 2, places=4)
        self.assertIsNone(M.cap_memory("cpu"))

    def test_bf16_bar(self):
        self.assertEqual(M.bar_outcome(0.0, 0.1, 1.0), "PASS")
        self.assertEqual(M.bar_outcome(0.2, 0.1, 1.0), "FAIL")
        self.assertEqual(M.bar_outcome(0.0, 0.1, 0.05), "VOID")
        r = M.grad_check(Tiny, SHAPE, "cpu", "cpu", seed=3, dev_amp=True)
        self.assertGreater(r["value"], 0.0)             # bf16 autocast moves the gradient: the bar is not zero

    def test_device_names(self):
        self.assertEqual(M.check_device("cpu"), "cpu")
        with self.assertRaises(ValueError):
            M.check_device("tpu")
        if not torch.backends.mps.is_available():
            with self.assertRaises(ValueError):
                M.check_device("mps")

    def test_cli_usage_errors(self):
        for argv in (["run", "--models", "nope", "--device", "cpu"], ["run", "--device", "tpu"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                M.main(argv)
            self.assertEqual(cm.exception.code, 2)

    def test_list(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(M.main(["list"]), 0)
        for name in M.MODELS:
            self.assertIn(name, out.getvalue())


@unittest.skipUnless(HAVE_TORCH, "torch not installed")
class Networks(unittest.TestCase):
    """The built-in networks, and a network from a script of your own."""

    def test_every_network_builds_and_runs_on_its_small_shape(self):
        for name, spec in M.MODELS.items():
            net = spec["build"](M.load_script(name)).eval()
            with torch.no_grad():
                out = M.flat_out(net(M.make_input(spec["small"], 0)))
            self.assertTrue(torch.isfinite(out).all(), name)

    def test_run_model_on_cpu_passes(self):
        for name in M.MODELS:
            rec = M.run_model(name, "cpu", "cpu", steps=2)
            self.assertEqual(rec["outcome"], "PASS", rec)

    def test_bf16_bar_on_cpu(self):
        rec = M.run_model("conv3d", "cpu", "cpu", steps=2, bar="bf16")
        self.assertEqual(rec["outcome"], "PASS", rec)
        self.assertTrue(all("fixed_tol_outcome" in c for c in rec["checks"]))

    def test_custom_script(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mynet.py"
            path.write_text("import torch\n\ndef Net():\n    return torch.nn.Sequential(torch.nn.Conv3d(1, 4, 3, padding=1),"
                            " torch.nn.ReLU(), torch.nn.Conv3d(4, 1, 1))\n")
            out_json = Path(d) / "rec.json"
            out = io.StringIO()
            with redirect_stdout(out):
                code = M.main(["run", "--device", "cpu", "--script", str(path), "--build", "Net",
                               "--shape", "2,1,8,8,8", "--steps", "2", "--out", str(out_json)])
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("custom: PASS", out.getvalue())
            import json
            rec = json.loads(out_json.read_text())
            self.assertEqual([m["model"] for m in rec["models"]], ["custom"])

    def test_custom_usage_errors(self):
        for argv in (["run", "--device", "cpu", "--script", "x.py"],
                     ["run", "--device", "cpu", "--script", "x.py", "--build", "Net", "--shape", "2,1"],
                     ["run", "--device", "cpu", "--script", "x.py", "--build", "Net", "--shape", "a,b,c"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                M.main(argv)
            self.assertEqual(cm.exception.code, 2, argv)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            M.main(["run", "--device", "cpu", "--script", "no/such/net.py", "--build", "Net", "--shape", "2,1,8,8,8"])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(M.parse_shape("2,1,8,8,8"), (2, 1, 8, 8, 8))


if __name__ == "__main__":
    unittest.main()
