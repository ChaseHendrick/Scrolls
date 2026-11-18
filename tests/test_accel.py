"""kit/accel.py: device order (CUDA, then MPS, then CPU), precision choice per device, the --fp32 path,
autocast and GradScaler wiring. CUDA and MPS are simulated with mocks; the CPU paths run for real."""
import argparse
import contextlib
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from kit import accel  # noqa: E402  (imports without torch)

try:
    import torch
except ImportError:
    torch = None


def machine(cuda=False, mps=False, capability=(9, 0), count=1, mps_autocast=True):
    """Patch torch so it looks like a machine with the given accelerators."""
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(torch.cuda, 'is_available', return_value=cuda))
    stack.enter_context(mock.patch.object(torch.cuda, 'device_count', return_value=count if cuda else 0))
    stack.enter_context(mock.patch.object(torch.cuda, 'get_device_capability', return_value=capability))
    stack.enter_context(mock.patch.object(torch.backends.mps, 'is_available', return_value=mps))
    stack.enter_context(mock.patch.object(accel, 'mps_autocast_available', return_value=mps_autocast))
    return stack


class NoTorchImport(unittest.TestCase):
    def test_kit_accel_imports_without_torch(self):
        code = ('import sys; sys.modules["torch"] = None; sys.path.insert(0, %r); from kit import accel; '
                'print(accel.device_type("cuda:1"), accel.normalize_precision("bfloat16"))' % ROOT)
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.split(), ['cuda', 'bf16'])

    def test_names(self):
        self.assertEqual(accel.device_type('cuda:1'), 'cuda')
        self.assertEqual(accel.device_type('mps'), 'mps')
        self.assertEqual(accel.device_type(' CPU '), 'cpu')
        for alias, name in (('none', 'fp32'), ('float16', 'fp16'), ('half', 'fp16'), ('BF16', 'bf16'),
                            (None, 'auto')):
            self.assertEqual(accel.normalize_precision(alias), name)
        with self.assertRaises(ValueError):
            accel.normalize_precision('int8')


@unittest.skipIf(torch is None, 'torch not installed')
class Devices(unittest.TestCase):
    def test_auto_prefers_cuda_then_mps_then_cpu(self):
        with machine(cuda=True, mps=True):
            self.assertEqual(accel.resolve_device('auto'), 'cuda')
        with machine(cuda=False, mps=True):
            self.assertEqual(accel.resolve_device('auto'), 'mps')
            self.assertEqual(accel.resolve_device(None), 'mps')
        with machine(cuda=False, mps=False):
            self.assertEqual(accel.resolve_device('auto'), 'cpu')

    def test_explicit_devices_are_checked_not_silently_replaced(self):
        with machine(cuda=False, mps=False):
            for name in ('cuda', 'cuda:0', 'mps'):
                with self.assertRaises(ValueError):
                    accel.resolve_device(name)
            self.assertEqual(accel.resolve_device('cpu'), 'cpu')
        with machine(cuda=True, count=2):
            self.assertEqual(accel.resolve_device('cuda:1'), 'cuda:1')
            with self.assertRaises(ValueError):
                accel.resolve_device('cuda:2')
        with self.assertRaises(ValueError):
            accel.resolve_device('gpu')
        with self.assertRaises(ValueError):
            accel.resolve_device('meta')


@unittest.skipIf(torch is None, 'torch not installed')
class Precision(unittest.TestCase):
    def test_auto_per_device(self):
        with machine(cuda=True, capability=(8, 0)):
            self.assertEqual(accel.resolve_precision('cuda', 'auto'), 'bf16')
            self.assertEqual(accel.resolve_precision('cuda:0', 'auto'), 'bf16')
        with machine(cuda=True, capability=(7, 5)):
            self.assertEqual(accel.resolve_precision('cuda', 'auto'), 'fp16')
            with self.assertRaises(ValueError):
                accel.resolve_precision('cuda', 'bf16')
        with machine(mps=True):
            self.assertEqual(accel.resolve_precision('mps', 'auto'), 'fp32')    # measured: no faster on an M1 Pro
            self.assertEqual(accel.resolve_precision('mps', 'fp16'), 'fp16')
            self.assertEqual(accel.resolve_precision('mps', 'bf16'), 'bf16')
        with machine(mps=True, mps_autocast=False):
            self.assertEqual(accel.resolve_precision('mps', 'auto'), 'fp32')
            with self.assertRaises(ValueError):
                accel.resolve_precision('mps', 'fp16')
        self.assertEqual(accel.resolve_precision('cpu', 'auto'), 'fp32')
        self.assertEqual(accel.resolve_precision('cpu', 'bf16'), 'bf16')

    def test_fp32_never_autocasts_anywhere(self):
        for device in ('cpu', 'cuda', 'cuda:3', 'mps'):
            self.assertEqual(accel.resolve_precision(device, 'fp32'), 'fp32')
            self.assertIsInstance(accel.autocast(device, 'fp32'), contextlib.nullcontext)
            self.assertFalse(accel.grad_scaler(device, 'fp32').is_enabled())
        self.assertIsNone(accel.dtype('fp32'))

    def test_cpu_autocast_really_casts(self):
        a = torch.randn(4, 4)
        with accel.autocast('cpu', 'bf16'):
            self.assertEqual((a @ a).dtype, torch.bfloat16)
        with accel.autocast('cpu', 'auto'):
            self.assertEqual((a @ a).dtype, torch.float32)
        with accel.autocast('cpu', 'fp32'):
            self.assertEqual((a @ a).dtype, torch.float32)

    def test_autocast_gets_the_bare_device_type(self):
        with machine(cuda=True, capability=(9, 0)), mock.patch.object(torch, 'autocast') as ac:
            accel.autocast('cuda:1', 'auto')
        ac.assert_called_once_with(device_type='cuda', dtype=torch.bfloat16)
        with machine(mps=True), mock.patch.object(torch, 'autocast') as ac:
            accel.autocast('mps', 'fp16')
        ac.assert_called_once_with(device_type='mps', dtype=torch.float16)
        with machine(mps=True), mock.patch.object(torch, 'autocast') as ac:
            accel.autocast('mps', 'auto')                 # auto is fp32 on MPS: no autocast
        ac.assert_not_called()

    def test_grad_scaler_only_for_fp16_on_a_gpu(self):
        with machine(mps=True):
            self.assertTrue(accel.grad_scaler('mps', 'fp16').is_enabled())
            self.assertFalse(accel.grad_scaler('mps', 'bf16').is_enabled())
        self.assertFalse(accel.grad_scaler('cpu', 'fp16').is_enabled())
        self.assertFalse(accel.grad_scaler('cpu', 'bf16').is_enabled())

    def test_synchronize_is_a_no_op_on_cpu(self):
        accel.synchronize('cpu')
        with mock.patch.object(torch.mps, 'synchronize') as sync:
            accel.synchronize('mps')
        sync.assert_called_once_with()


@unittest.skipIf(torch is None, 'torch not installed')
class Arguments(unittest.TestCase):
    def parse(self, argv, **kw):
        return accel.from_args(accel.add_arguments(argparse.ArgumentParser(), **kw).parse_args(argv))

    def test_flags(self):
        with machine(cuda=True, capability=(10, 0)):
            self.assertEqual(self.parse([]), ('cuda', 'bf16'))
            self.assertEqual(self.parse(['--fp32']), ('cuda', 'fp32'))
            self.assertEqual(self.parse(['--precision', 'fp16']), ('cuda', 'fp16'))
            self.assertEqual(self.parse(['--device', 'cpu']), ('cpu', 'fp32'))
            with self.assertRaises(ValueError):
                self.parse(['--fp32', '--precision', 'bf16'])
        with machine(mps=True):
            self.assertEqual(self.parse([]), ('mps', 'fp32'))
            self.assertEqual(self.parse(['--precision', 'fp16']), ('mps', 'fp16'))
            self.assertEqual(self.parse(['--precision', 'none']), ('mps', 'fp32'))
        with machine():
            self.assertEqual(self.parse([], precision='fp32'), ('cpu', 'fp32'))

    def test_describe_and_cli(self):
        record = accel.describe('cpu', 'bf16')
        self.assertEqual((record['device'], record['precision'], record['autocast_dtype']), ('cpu', 'bf16', 'bfloat16'))
        self.assertIsNone(accel.describe('cpu', 'auto')['autocast_dtype'])
        out = subprocess.run([sys.executable, '-m', 'kit.accel', '--device', 'cpu'], cwd=ROOT,
                             capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout)['precision'], 'fp32')


    def test_check_passes_on_the_cpu_and_its_control_is_caught(self):
        for precision in ('fp32', 'bf16', 'fp16'):
            r = accel.check('cpu', precision)
            self.assertTrue(r['ok'], r)
            self.assertLessEqual(r['max_diff'], r['tolerance'])
            self.assertGreater(r['control_max_diff'], accel.CONTROL_FACTOR * r['tolerance'])
        self.assertEqual(accel.check('cpu', 'fp32')['max_diff'], 0.0)

    def test_check_can_fail(self):
        """A device path that returns other numbers fails, and so does a control that is not caught."""
        calls = []

        def shift_the_third_run(module, inputs, output):  # runs: reference, control, then the device under test
            if isinstance(module, torch.nn.Sequential):
                calls.append(1)
                if len(calls) == 3:
                    return output + 1.0
        handle = torch.nn.modules.module.register_module_forward_hook(shift_the_third_run)
        try:
            r = accel.check('cpu', 'fp32')
        finally:
            handle.remove()
        self.assertFalse(r['agrees'])
        self.assertFalse(r['ok'])
        with mock.patch.object(accel, 'CONTROL_FACTOR', 1e6):
            r = accel.check('cpu', 'fp32')
        self.assertTrue(r['agrees'])
        self.assertFalse(r['control_caught'])
        self.assertFalse(r['ok'])

    def test_check_bounds_fp32_on_cuda_by_tf32(self):
        """CUDA lets cuDNN convolutions use TF32 by default, so fp32 there gets the TF32 bound; with TF32 off it is
        held to plain fp32. CUDA is simulated: the device type is patched and the run stays on the CPU."""
        kind = accel.device_type
        flags = torch.backends.cudnn.allow_tf32, torch.backends.cuda.matmul.allow_tf32

        def tf32(cudnn, matmul):        # torch's flags are properties that mock cannot restore, so set them here
            torch.backends.cudnn.allow_tf32, torch.backends.cuda.matmul.allow_tf32 = cudnn, matmul
        self.addCleanup(tf32, *flags)
        with mock.patch.object(accel, 'device_type', side_effect=lambda d: 'cuda' if kind(d) == 'cpu' else kind(d)), \
                mock.patch.object(accel, 'synchronize'):
            tf32(True, False)                                   # torch's CUDA defaults
            r = accel.check('cpu', 'fp32')
            self.assertEqual((r['tf32_allowed'], r['tolerance']), (True, accel.TOLERANCE['tf32']))
            tf32(False, False)
            r = accel.check('cpu', 'fp32')
            self.assertEqual((r['tf32_allowed'], r['tolerance']), (False, accel.TOLERANCE['fp32']))
            tf32(*flags)
        self.assertFalse(accel.check('cpu', 'fp32')['tf32_allowed'])
        self.assertGreater(6.6, accel.CONTROL_FACTOR * accel.TOLERANCE['tf32'])   # the control still has room

    def test_check_cli_exit_status(self):
        out = subprocess.run([sys.executable, '-m', 'kit.accel', '--check', '--device', 'cpu', '--precision', 'bf16'],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(json.loads(out.stdout)['ok'])
        out = subprocess.run([sys.executable, '-m', 'kit.accel', '--device', 'cpu', '--fp32', '--precision', 'bf16'],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)


if __name__ == '__main__':
    unittest.main()
