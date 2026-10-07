"""CPU-only synthetic guards for an unrun job; no Modal calls or model training."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT/'scripts/experiments/2026-10-07-cloud/laneH-finetune'


def load(name):
    spec = importlib.util.spec_from_file_location('laneh_' + name, JOB/(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SafetyTests(unittest.TestCase):
    def run_shell(self, work, **settings):
        env = dict(os.environ, WORK=str(work), OUT=str(work/'out'), PATH='/nonexistent')
        for key in ('PHASE', 'LANEH_EXECUTE', 'LANEH_GPU_AUTHORIZED', 'SMOKE_STEPS'):
            env.pop(key, None)
        env.update(settings)
        return subprocess.run(['/bin/bash', str(JOB/'run_job.sh')], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=5)

    def test_shell_default_is_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)/'absent'
            result = self.run_shell(work)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Not run', result.stdout)
            self.assertFalse(work.exists())

    def test_shell_execution_and_gpu_need_separate_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)/'absent'
            result = self.run_shell(work, PHASE='prepare')
            self.assertEqual(result.returncode, 2)
            self.assertIn('LANEH_EXECUTE', result.stderr)
            for phase in ('base', 'variant', 'all'):
                result = self.run_shell(work, PHASE=phase, LANEH_EXECUTE='1')
                self.assertEqual(result.returncode, 2)
                self.assertIn('No GPU execution', result.stderr)
            self.assertFalse(work.exists())

    def test_modal_default_refuses_before_remote_call(self):
        class Image:
            @classmethod
            def debian_slim(cls, **kwargs): return cls()
            def apt_install(self, *args): return self
            def run_commands(self, *args): return self
        class App:
            def __init__(self, *args): pass
            def function(self, **kwargs): return lambda fn: fn
            def local_entrypoint(self): return lambda fn: fn
        stub = types.SimpleNamespace(Image=Image, App=App,
                                     Volume=types.SimpleNamespace(from_name=lambda *a, **k: object()))
        with patch.dict(sys.modules, {'modal': stub}):
            module = load('modal_app')
        with self.assertRaisesRegex(ValueError, 'no remote launch'):
            module.main()
        with self.assertRaisesRegex(ValueError, 'nonnegative'):
            module._run('base', -1, 'a'*40)

    def test_collector_empty_and_partial_remain_descriptive(self):
        module = load('collect')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            empty = module.collect(path)
            self.assertEqual(empty[0]['status'], 'not run')
            self.assertEqual(len(empty[0]['missing_score_keys']), 20)
            (path/'scores').mkdir()
            score = {'forward': {'auc': .6}, 'control': {'auc': .5}}
            for segment in ('0841-w00', 'w045'):
                (path/'scores'/('S1_' + segment + '.json')).write_text(json.dumps(score))
            rows = module.collect(path, smoke=True)
            self.assertEqual(rows[0]['status'], 'partial')
            self.assertEqual(rows[0]['completed_score_rows'], 2)
            self.assertTrue(rows[1]['primary_for_arm'])
            self.assertFalse(rows[2]['primary_for_arm'])
            self.assertTrue(all(row['smoke'] for row in rows))
            self.assertNotIn('verdict', rows[1])

    def test_collector_missing_controls_and_unknown_scores_refused(self):
        module = load('collect')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); (path/'scores').mkdir()
            file = path/'scores/base_w045.json'
            file.write_text(json.dumps({'forward': {'auc': .6}}))
            with self.assertRaisesRegex(ValueError, 'reverse control'):
                module.collect(path)
            file.rename(path/'scores/unknown.json')
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                module.collect(path)

    def test_collector_refuses_historical_output_overwrite(self):
        module = load('collect')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'results.json'; output.write_text('historical')
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                module.main([directory, str(output)])
            self.assertEqual(output.read_text(), 'historical')

    def test_cache_receipt_binds_bytes_and_settings(self):
        module = load('protocol')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); data = path/'data'; data.mkdir()
            (data/'chunk').write_bytes(b'original'); receipt = path/'receipt.json'
            with self.assertRaisesRegex(ValueError, 'no binding'):
                module.bind(receipt, [data], {'stride': '128'})
            module.bind(receipt, [data], {'stride': '128'}, create=True)
            frozen = receipt.read_bytes()
            module.bind(receipt, [data], {'stride': '128'})
            with self.assertRaisesRegex(ValueError, 'changed'):
                module.bind(receipt, [data], {'stride': '64'})
            (data/'chunk').write_bytes(b'mutated!')
            with self.assertRaisesRegex(ValueError, 'changed'):
                module.bind(receipt, [data], {'stride': '128'})
            self.assertEqual(receipt.read_bytes(), frozen)


try:
    import numpy as np
except ImportError:
    np = None

try:
    import zarr
except ImportError:
    zarr = None


@unittest.skipIf(np is None or zarr is None, 'requires numpy and zarr')
class CropTests(unittest.TestCase):
    def test_crop_recipe_and_output_are_bound_and_partial_refused(self):
        module = load('protocol')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); source = path/'source.zarr'; out = path/'crop.zarr'
            data = np.arange(3*7*8, dtype=np.uint16).reshape(3, 7, 8)
            zarr.open_group(source, mode='w').create_array('0', data=data)
            module.create_crop(source, out, [1, 5, 2, 6], 'stored')
            np.testing.assert_array_equal(zarr.open(out, mode='r')['0'][:], data[:, 1:5, 2:6])
            module.create_crop(source, out, [1, 5, 2, 6], 'stored')
            with self.assertRaisesRegex(ValueError, 'changed'):
                module.create_crop(source, out, [1, 5, 2, 6], 'shuffled')
            zarr.open(out, mode='r+')['0'][0, 0, 0] = 999
            with self.assertRaisesRegex(ValueError, 'changed'):
                module.create_crop(source, out, [1, 5, 2, 6], 'stored')
            changed_source = path/'source-change.zarr'
            module.create_crop(source, changed_source, [1, 5, 2, 6], 'stored')
            zarr.open(source, mode='r+')['0'][0, 0, 0] = 999
            with self.assertRaisesRegex(ValueError, 'changed'):
                module.create_crop(source, changed_source, [1, 5, 2, 6], 'stored', verify_only=True)
            stale = path/'stale.zarr'; stale.mkdir()
            with self.assertRaisesRegex(ValueError, 'no binding'):
                module.create_crop(source, stale, [1, 5, 2, 6], 'stored')

    def test_missing_and_receipt_only_crops_are_not_created_during_verification(self):
        module = load('protocol')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); source = path/'source.zarr'; out = path/'crop.zarr'
            zarr.open_group(source, mode='w').create_array('0', data=np.zeros((3, 7, 8), np.uint16))
            with self.assertRaisesRegex(ValueError, 'missing'):
                module.create_crop(source, out, [1, 5, 2, 6], 'stored', verify_only=True)
            self.assertFalse(out.exists())
            Path(str(out) + '.binding.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'partial'):
                module.create_crop(source, out, [1, 5, 2, 6], 'stored', verify_only=True)
            self.assertFalse(out.exists())

    def test_base_phase_checks_crop_binding_before_gpu_or_inference(self):
        module = load('protocol')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory); out = work/'out'; (out/'crops').mkdir(parents=True)
            (work/'venv/bin').mkdir(parents=True)
            (work/'venv/bin/python').symlink_to(sys.executable)
            base = work/'checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth'
            base.parent.mkdir(parents=True); base.write_bytes(b'synthetic, never loaded')
            sources = [base]
            for name in ('0841-w00_9um.zarr', 'w045_9um.zarr', '0841-w00_labels', 'w045_labels'):
                source = work/'data'/name; source.mkdir(parents=True)
                (source/'chunk').write_bytes(b'synthetic source')
                sources.append(source)
            revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
            settings = {'scrolls': revision, 'villa': load('training_guard').VILLA_REVISION, 'smoke_steps': '0'}
            module.bind(out/'input-binding.json', sources, settings, create=True)
            (out/'crops/0841-w00_stored.zarr').mkdir()  # Existing unbound cache, as in the original failure.
            env = dict(os.environ, WORK=str(work), OUT=str(out), PHASE='base',
                       LANEH_EXECUTE='1', LANEH_GPU_AUTHORIZED='1', SMOKE_STEPS='0')
            result = subprocess.run(['/bin/bash', str(JOB/'run_job.sh')], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('no binding receipt', result.stderr)
            self.assertNotIn('no CUDA', result.stderr)
            self.assertFalse(any((out/'maps').iterdir()))

    def test_shuffled_crop_preserves_frozen_depth_permutation(self):
        module = load('protocol')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); source = path/'source.zarr'; out = path/'crop.zarr'
            data = np.arange(6*7*8, dtype=np.uint16).reshape(6, 7, 8)
            zarr.open_group(source, mode='w').create_array('0', data=data)
            module.create_crop(source, out, [1, 5, 2, 6], 'shuffled')
            expected = data[np.random.default_rng(20261007).permutation(6), 1:5, 2:6]
            np.testing.assert_array_equal(zarr.open(out, mode='r')['0'][:], expected)
            with self.assertRaises(ValueError):
                module.create_crop(source, path/'invalid.zarr', [0, 99, 0, 1], 'stored')


@unittest.skipIf(np is None, 'requires numpy')
class MaskTests(unittest.TestCase):
    def setUp(self): self.guard = load('training_guard')

    def test_patch_exclusion_matches_geometric_oracle(self):
        shape, boxes, gap, size = (13, 15), [(2, 4, 1, 3), (8, 11, 10, 14)], 1, 3
        actual = self.guard.allowed_mask(shape, boxes, gap, size)
        for y in range(shape[0]):
            for x in range(shape[1]):
                expected = y + size <= shape[0] and x + size <= shape[1]
                for a, b, c, d in boxes:
                    overlaps = y < b + gap and y + size > a - gap and x < d + gap and x + size > c - gap
                    expected &= not overlaps
                self.assertEqual(bool(actual[y, x]), bool(expected), (y, x))

    def test_invalid_exclusions_fail_closed(self):
        for boxes, gap, size in (([], 0, 2), ([(0, 2, 0, 2)], -1, 2),
                                  ([(0, 20, 0, 2)], 0, 2), ([(0, 2, 0, 2)], 0, 20),
                                  ([(0, 0, 0, 2)], 0, 2), ([(0., 2, 0, 2)], 0, 2)):
            with self.assertRaises(ValueError):
                self.guard.allowed_mask((10, 10), boxes, gap, size)

    def test_excluded_weights_do_not_mutate_original(self):
        weight = np.ones((10, 10), np.float32)
        out = self.guard.exclude_targets(weight, [(2, 4, 3, 5)], 1, 2)
        expected = weight.copy(); expected[1:5, 2:6] = 0
        np.testing.assert_array_equal(out, expected)
        self.assertTrue(weight.all())

    def test_uint8_quantization_and_zero_unknown(self):
        target, weight = self.guard.pseudo_targets(np.array([[0, 1, 20, 240, 255]], np.uint8), .9, .1)
        np.testing.assert_array_equal(target, [[0, 0, 0, 1, 1]])
        np.testing.assert_array_equal(weight, [[0, 1, 1, 1, 1]])
        target, weight = self.guard.pseudo_targets(np.ones((2, 2), np.uint8), .9, .1)
        self.assertFalse(target.any()); self.assertTrue(weight.all())

    def test_invalid_probabilities_and_thresholds_refused(self):
        for values in (np.array([[np.nan]]), np.array([[np.inf]]), np.array([[-.1]]),
                       np.array([[1.1]]), np.array([[1]], np.uint16)):
            with self.assertRaises(ValueError): self.guard.pseudo_targets(values, .9, .1)
        with self.assertRaises(ValueError): self.guard.pseudo_targets(np.ones((1, 1)), .1, .9)


try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None or np is None, 'requires CPU torch and numpy')
class TensorTests(unittest.TestCase):
    def test_unknown_values_cannot_change_pooled_supervised_target(self):
        import torch.nn.functional as functional
        torch.set_num_threads(1)
        guard = load('training_guard')
        weights = torch.tensor([[[[1., 1.], [1., 0.]]]])
        outputs = []
        for unknown in (0., 1., float('nan')):
            target = torch.tensor([[[[1., 1.], [0., unknown]]]])
            label, known = guard.pooled_targets(functional, target, weights, (1, 1))
            outputs.append((label.item(), known.item()))
        self.assertEqual(outputs, [(1., 1.)]*3)
        label, known = guard.pooled_targets(functional, target, weights*0, (1, 1))
        self.assertEqual((label.item(), known.item()), (0., 0.))


if __name__ == '__main__': unittest.main()
